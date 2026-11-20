"""Answer generation: the LLM explains, the rules decide.

The coverage decision is taken by the rules in agent.py. This module only
writes the sentence shown to the claims handler:

- `ollama_generate(prompt)` asks the model of `llm.model` (through a local Ollama
  server), with thinking mode off; any reasoning text the model still writes
  (`... </think>`) is removed, only the answer is kept; a reasoning model cut by
  `max_tokens` gives no answer (its text may be reasoning without any tag);
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
from dataclasses import dataclass
from functools import cache

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


@dataclass
class OllamaAnswer:
    """The answer text plus what tracing needs (token counts from Ollama)."""

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def ollama_generate(prompt: str) -> str:
    """Send the prompt to the local Ollama server and return the generated text."""
    return ollama_call(prompt).text


def ollama_call(prompt: str) -> OllamaAnswer:
    """Same as ollama_generate, but also returns the model and the token counts."""
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
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise GeneratorUnavailable(f"Ollama ({host}, model {cfg['model']}): {error}") from error
    # Guard: a reasoning model stopped by max_tokens may have written only (part of)
    # its reasoning, without any tag to remove it. Never use such a text.
    if data.get("done_reason") == "length" and is_reasoning_model(host, cfg["model"]):
        raise GeneratorUnavailable(f"answer cut by max_tokens ({cfg['max_tokens']}) "
                                   f"on the reasoning model {cfg['model']}")
    text = strip_thinking(data.get("response", ""))
    if not text:
        raise GeneratorUnavailable("Ollama returned an empty answer (or only reasoning text)")
    return OllamaAnswer(text=text, model=cfg["model"], input_tokens=data.get("prompt_eval_count"),
                        output_tokens=data.get("eval_count"))


@cache
def is_reasoning_model(host: str, model: str) -> bool:
    """Does Ollama list "thinking" in the model's capabilities? False if it cannot tell."""
    request = urllib.request.Request(f"{host}/api/show",
                                     data=json.dumps({"model": model}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            info = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    return "thinking" in info.get("capabilities", [])


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


PROMPT_VARIANTS = ("current", "explain_rule", "formula_hint")
# Guarantees that pay for the third party only (not for the customer's own car).
THIRD_PARTY_ONLY = {"rc", "defense_recours"}


def formula_hint(formula: str, bought: list[str]) -> str:
    """What the formula pays for, from config.yaml `formulas` (prompt_variant formula_hint)."""
    own = [GUARANTEE_FR.get(g, g) for g in bought if g not in THIRD_PARTY_ONLY]
    if not own:
        return (f"La formule {formula} ne contient que la responsabilité civile et la défense "
                "et recours : elle paie les dommages causés aux autres, mais PAS les dommages "
                "au véhicule de l'assuré.")
    return (f"La formule {formula} paie les dommages au véhicule de l'assuré uniquement par "
            f"ces garanties : {', '.join(own)}. Un sinistre n'est couvert que si une des "
            "garanties pouvant le couvrir fait partie de la formule.")


def build_prompt(claim_text: str, insurer: str, formula: str, bought: list[str],
                 cause: str | None, damages_fr: list[str], needed: list[str],
                 clauses: list[dict], covered: bool | None = None,
                 variant: str | None = None) -> str:
    """Everything the LLM is allowed to use: the claim and the retrieved clauses.

    variant (default: llm.prompt_variant in config.yaml):
    - "current": the original prompt (the LLM gives its own verdict);
    - "explain_rule": the prompt gives the rules' verdict (`covered`) and asks the
      LLM only to explain it with the clauses;
    - "formula_hint": the original prompt + what the contract formula pays for.
    """
    variant = variant or CONFIG["llm"].get("prompt_variant", "current")
    if variant not in PROMPT_VARIANTS:
        raise ValueError(f"unknown llm.prompt_variant {variant!r} (one of {PROMPT_VARIANTS})")
    if variant == "explain_rule" and covered is None:
        raise ValueError("prompt_variant explain_rule needs the rules' verdict (covered)")
    example = clauses[0]["clause_id"] if clauses else "AXA-015"
    included = ", ".join(GUARANTEE_FR.get(g, g) for g in bought)
    useful = ", ".join(GUARANTEE_FR.get(g, g) for g in needed)
    if variant == "explain_rule":
        verdict = VERDICT_FR[covered]
        instructions = [
            f"La décision a déjà été prise par les règles du contrat : « Décision : {verdict} ».",
            (f"Commence ta réponse exactement par « Décision : {verdict} », puis explique "
             "pourquoi avec les clauses. Ne change pas la décision."),
        ]
    else:
        instructions = [
            "Commence par « Décision : COUVERT » ou « Décision : NON COUVERT », puis explique."]
    contract = [(f"Contrat : {insurer}, formule {formula}. Garanties incluses dans la formule : "
                 f"{included}.")]
    if variant == "formula_hint":
        contract.append(formula_hint(formula, bought))
    lines = [
        "Tu es un assistant pour gestionnaires de sinistres automobiles.",
        ("Réponds en français, en 2 ou 3 phrases, en utilisant UNIQUEMENT la déclaration "
         "et les clauses ci-dessous. N'invente rien."),
        *instructions,
        f"Cite les identifiants des clauses utilisées entre crochets, par exemple [{example}].",
        "",
        f"Déclaration du client : {claim_text}",
        f"Dommages vus sur les photos : {', '.join(damages_fr) or 'aucun'}",
        f"Cause du sinistre : {CAUSE_FR[cause] if cause else 'non précisée dans la déclaration'}",
        *contract,
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
