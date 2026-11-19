"""Answer generation: the LLM explains, the rules decide.

The coverage decision is taken by the rules in agent.py. This module only
writes the sentence shown to the claims handler:

- `ollama_generate(prompt)` asks the model of `llm.model` (through a local Ollama
  server), with thinking mode off; any reasoning text the model still writes
  (`... </think>`) is removed, only the answer is kept;
- `template_answer(...)` builds the same kind of answer without any model. It
  is used when Ollama is not reachable or slower than `llm.timeout_seconds`.

A generator is just a function `prompt -> text`, so tests pass a fake one.
"""
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable

from agents.policy.rules import normalize
from agents.policy.settings import CONFIG

Generator = Callable[[str], str]

GUARANTEE_FR = {
    "collision": "collision", "tous_risques": "tous risques", "bris_de_glace": "bris de glace",
    "vol": "vol", "incendie": "incendie", "vandalisme": "vandalisme",
    "catastrophe_naturelle": "catastrophe naturelle", "rc": "responsabilité civile",
    "defense_recours": "défense et recours",
}
CAUSE_FR = GUARANTEE_FR | {"collision": "collision / accident"}
VERDICT_FR = {True: "COUVERT", False: "NON COUVERT"}

CITATION = re.compile(r"\[([A-Z]+-\d+(?:-\d+)?)\]")
VERDICT = re.compile(r"decision\s*(non couvert|couvert)")
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


class GeneratorUnavailable(RuntimeError):
    """The LLM cannot answer (not running, model missing, too slow, disabled)."""


def no_generator(prompt: str) -> str:
    """A generator that always fails: forces the template answer (tests, CI)."""
    raise GeneratorUnavailable("LLM disabled")


def ollama_generate(prompt: str) -> str:
    """Send the prompt to the local Ollama server and return the generated text."""
    cfg = CONFIG["llm"]
    host = os.getenv("OLLAMA_HOST", cfg["host"]).rstrip("/")
    if not host.startswith("http"):
        host = f"http://{host}"
    body = json.dumps({
        "model": cfg["model"], "prompt": prompt, "stream": False,
        "think": False,              # reasoning models (qwen3): no thinking mode
        "options": {"temperature": cfg["temperature"], "num_predict": cfg["max_tokens"]},
    }).encode("utf-8")
    request = urllib.request.Request(f"{host}/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=cfg["timeout_seconds"]) as response:
            text = json.loads(response.read().decode("utf-8")).get("response", "")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise GeneratorUnavailable(f"Ollama ({host}, model {cfg['model']}): {error}") from error
    text = strip_thinking(text)
    if not text:
        raise GeneratorUnavailable("Ollama returned an empty answer (or only reasoning text)")
    return text


def strip_thinking(text: str) -> str:
    """Keep only the answer of a reasoning model.

    Some models (qwen3:4b) still reason when thinking mode is off. The reasoning
    comes either as "<think>...</think>" or, when the opening tag is in the
    model's prompt template, as "...</think>" followed by the answer. Reasoning
    cut by `max_tokens` ("<think>..." never closed) leaves no answer: "".
    """
    text = THINK_BLOCK.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    elif "<think>" in text:
        text = ""
    return text.strip()


def default_generator() -> Generator:
    return ollama_generate if CONFIG["llm"]["enabled"] else no_generator


def build_prompt(claim_text: str, insurer: str, formula: str, bought: list[str],
                 cause: str | None, damages_fr: list[str], needed: list[str],
                 clauses: list[dict]) -> str:
    """Everything the LLM is allowed to use: the claim and the retrieved clauses."""
    example = clauses[0]["clause_id"] if clauses else "AXA-015"
    included = ", ".join(GUARANTEE_FR.get(g, g) for g in bought)
    useful = ", ".join(GUARANTEE_FR.get(g, g) for g in needed)
    lines = [
        "Tu es un assistant pour gestionnaires de sinistres automobiles.",
        ("Réponds en français, en 2 ou 3 phrases, en utilisant UNIQUEMENT la déclaration "
         "et les clauses ci-dessous. N'invente rien."),
        "Commence par « Décision : COUVERT » ou « Décision : NON COUVERT », puis explique.",
        f"Cite les identifiants des clauses utilisées entre crochets, par exemple [{example}].",
        "",
        f"Déclaration du client : {claim_text}",
        f"Dommages vus sur les photos : {', '.join(damages_fr) or 'aucun'}",
        f"Cause du sinistre : {CAUSE_FR[cause] if cause else 'non précisée dans la déclaration'}",
        f"Contrat : {insurer}, formule {formula}. Garanties incluses dans la formule : {included}.",
        f"Garanties pouvant couvrir ce sinistre : {useful}.",
        "",
        "Clauses du contrat :",
    ]
    lines += [f"[{c['clause_id']}] {c['title']} : {c['text'][:700]}" for c in clauses]
    lines += ["", "Réponse :"]
    return "\n".join(lines)


def template_answer(covered: bool, insurer: str, formula: str, cause: str | None,
                    needed: list[str], matching: list[str], clauses: list[dict]) -> str:
    """The answer without LLM. Cites the clause ids like the LLM is asked to."""
    cause_fr = (f"Sinistre déclaré : {CAUSE_FR[cause]}." if cause else
                "Cause non précisée dans la déclaration : garantie déduite des dommages "
                "visibles sur les photos.")
    guarantee_ids = " ".join(f"[{c['clause_id']}]" for c in clauses if not c["is_exclusion"])
    exclusion_ids = " ".join(f"[{c['clause_id']}]" for c in clauses if c["is_exclusion"])
    if covered:
        text = (f"Décision : COUVERT. {cause_fr} La garantie « {GUARANTEE_FR[matching[0]]} » "
                f"fait partie de la formule {formula} ({insurer}) {guarantee_ids}.")
        text += (f" Sous réserve des exclusions {exclusion_ids} et de la franchise."
                 if exclusion_ids else " Sous réserve des exclusions et de la franchise.")
        return text
    needed_fr = ", ".join(GUARANTEE_FR.get(g, g) for g in needed)
    return (f"Décision : NON COUVERT. {cause_fr} La formule {formula} ({insurer}) n'inclut "
            f"pas les garanties nécessaires ({needed_fr}) {guarantee_ids} {exclusion_ids}"
            .rstrip() + ".")


def read_verdict(answer: str) -> bool | None:
    """What the LLM concluded: True (couvert), False (non couvert), None (not said)."""
    match = VERDICT.search(normalize(answer))
    if match is None:
        return None
    return match.group(1) == "couvert"


def cited_clauses(answer: str) -> list[str]:
    """Clause ids written between brackets in the answer: "[AXA-015]" -> "AXA-015"."""
    return CITATION.findall(answer)
