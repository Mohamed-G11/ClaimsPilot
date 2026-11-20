"""Ollama request and reasoning-text removal (no Ollama server: urlopen is faked)."""
import io
import json

import pytest

from agents.policy import evaluate, generation
from agents.policy.settings import CONFIG

ANSWER = "Décision : COUVERT. La collision est garantie [AXA-015]."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ANSWER, ANSWER),                                                  # normal model
        (f"<think>The user wants a decision.</think>\n\n{ANSWER}", ANSWER),  # full block
        (f"Okay, let me check the clauses.\n</think>\n\n{ANSWER}", ANSWER),  # opening tag in template
        ("<think>Okay, the user wants", ""),                               # cut by max_tokens
    ],
)
def test_strip_thinking_keeps_only_the_answer(raw, expected):
    assert generation.strip_thinking(raw) == expected


@pytest.fixture
def fake_ollama(monkeypatch):
    """Replace urlopen. /api/generate: records the JSON body sent, answers with
    fake["response"] and fake["done_reason"]; /api/show: fake["capabilities"]."""
    fake = {"response": ANSWER, "done_reason": "stop", "capabilities": ["completion"],
            "sent": None, "show_calls": 0}

    def urlopen(request, timeout):
        if request.full_url.endswith("/api/show"):
            fake["show_calls"] += 1
            answer = {"capabilities": fake["capabilities"]}
        else:
            fake["sent"] = json.loads(request.data.decode("utf-8"))
            fake["url"] = request.full_url
            answer = {"response": fake["response"], "done_reason": fake["done_reason"],
                      "prompt_eval_count": fake.get("prompt_eval_count")}
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    monkeypatch.setattr(generation.urllib.request, "urlopen", urlopen)
    generation.is_reasoning_model.cache_clear()
    yield fake
    generation.is_reasoning_model.cache_clear()


def test_ollama_request_turns_thinking_off(fake_ollama, monkeypatch):
    monkeypatch.setitem(CONFIG["llm"], "model", "qwen3:4b")
    assert generation.ollama_generate("Bonjour") == ANSWER
    assert fake_ollama["sent"]["think"] is False
    assert fake_ollama["sent"]["model"] == "qwen3:4b"


def test_reasoning_text_never_reaches_the_answer(fake_ollama):
    fake_ollama["response"] = f"Let me think about clause AXA-015.\n</think>\n\n{ANSWER}"
    answer = generation.ollama_generate("Bonjour")
    assert answer == ANSWER
    assert "think" not in answer


def test_only_reasoning_means_no_answer(fake_ollama):
    fake_ollama["response"] = "<think>Okay, the user is asking"
    with pytest.raises(generation.GeneratorUnavailable):
        generation.ollama_generate("Bonjour")


def test_reasoning_model_cut_by_max_tokens_gives_no_answer(fake_ollama):
    # untagged reasoning that even quotes the expected format: must never be used
    fake_ollama["response"] = "Okay, the user wants me to start with Décision : COUVERT"
    fake_ollama["done_reason"] = "length"
    fake_ollama["capabilities"] = ["completion", "thinking"]
    with pytest.raises(generation.GeneratorUnavailable, match="cut by max_tokens"):
        generation.ollama_generate("Bonjour")


def test_non_reasoning_model_cut_by_max_tokens_keeps_its_answer(fake_ollama):
    fake_ollama["done_reason"] = "length"
    assert generation.ollama_generate("Bonjour") == ANSWER
    assert fake_ollama["show_calls"] == 1


def test_capabilities_are_only_asked_when_the_answer_is_cut(fake_ollama):
    fake_ollama["capabilities"] = ["completion", "thinking"]
    assert generation.ollama_generate("Bonjour") == ANSWER          # done_reason "stop"
    assert fake_ollama["show_calls"] == 0


def test_model_option_overrides_the_config_for_the_run(monkeypatch, tmp_path):
    monkeypatch.setitem(CONFIG["llm"], "model", "model-from-config")   # restored after
    monkeypatch.setitem(CONFIG["llm"], "max_tokens", 220)
    monkeypatch.setattr(evaluate, "RESULTS_FILE", tmp_path / "eval_results.json")
    monkeypatch.setattr(evaluate, "load_cases", lambda path: [])  # no claim
    monkeypatch.setattr(evaluate, "warm_up", lambda: None)         # no Ollama call
    seen = {}

    def fake_evaluate(cases, generator=None):
        seen["model"] = CONFIG["llm"]["model"]
        seen["max_tokens"] = CONFIG["llm"]["max_tokens"]
        return {"metrics": {"llm_answers": 1}, "rows": []}

    monkeypatch.setattr(evaluate, "evaluate", fake_evaluate)
    evaluate.main(["--model", "qwen2.5:7b", "--max-tokens", "1024", "--no-mlflow"])
    assert seen == {"model": "qwen2.5:7b", "max_tokens": 1024}
    report = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    assert report["generator"] == "qwen2.5:7b"


def test_ollama_host_env_overrides_the_config_host(fake_ollama, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    generation.ollama_generate("Bonjour")
    assert fake_ollama["url"] == "http://ollama:11434/api/generate"


def test_without_ollama_host_the_config_host_is_used(fake_ollama, monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    generation.ollama_generate("Bonjour")
    assert fake_ollama["url"] == f"{CONFIG['llm']['host'].rstrip('/')}/api/generate"


# --- prompt variants (llm.prompt_variant) ------------------------------------------

PROMPT_ARGS = {
    "claim_text": "Un véhicule m'a percuté.", "insurer": "AXA", "formula": "TIERS",
    "bought": ["rc", "defense_recours"], "cause": "collision",
    "damages_fr": ["enfoncement pare-chocs arrière"], "needed": ["collision", "tous_risques"],
    "clauses": [{"clause_id": "AXA-015", "title": "Dommages collision",
                 "text": "Nous garantissons les dommages...", "is_exclusion": False}],
}


def test_explain_rule_is_the_configured_default():
    import yaml

    from agents.policy.settings import CONFIG_PATH

    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert config["llm"]["prompt_variant"] == "explain_rule"      # chosen on Nov 20


def test_current_variant_is_unchanged(monkeypatch):
    monkeypatch.setitem(CONFIG["llm"], "prompt_variant", "current")
    prompt = generation.build_prompt(**PROMPT_ARGS, covered=False)
    assert prompt == generation.build_prompt(**PROMPT_ARGS)            # covered not used
    assert "Commence par « Décision : COUVERT » ou « Décision : NON COUVERT »" in prompt
    assert "déjà été prise" not in prompt and "ne contient que" not in prompt


def test_explain_rule_gives_the_rule_verdict_and_asks_only_to_explain():
    prompt = generation.build_prompt(**PROMPT_ARGS, covered=False, variant="explain_rule")
    assert "déjà été prise par les règles du contrat : « Décision : NON COUVERT »" in prompt
    assert "Commence ta réponse exactement par « Décision : NON COUVERT »" in prompt
    assert "ou « Décision : NON COUVERT »" not in prompt                # no free choice
    covered = generation.build_prompt(**PROMPT_ARGS, covered=True, variant="explain_rule")
    assert "« Décision : COUVERT »" in covered


def test_explain_rule_asks_for_two_short_sentences_with_the_real_reason():
    prompt = generation.build_prompt(**PROMPT_ARGS, covered=False, variant="explain_rule")
    assert "2 phrases courtes (50 mots au maximum en tout)" in prompt
    assert "Donne la vraie raison : la garantie concernée et si la formule du contrat" in prompt
    assert "en 2 ou 3 phrases" not in prompt                        # no conflicting length
    assert "Cite les identifiants des clauses" in prompt


def test_explain_rule_without_a_verdict_is_an_error():
    with pytest.raises(ValueError):
        generation.build_prompt(**PROMPT_ARGS, variant="explain_rule")


def test_formula_hint_says_tiers_does_not_pay_for_the_own_car():
    prompt = generation.build_prompt(**PROMPT_ARGS, variant="formula_hint")
    assert "PAS les dommages au véhicule de l'assuré" in prompt
    assert "Commence par « Décision : COUVERT » ou « Décision : NON COUVERT »" in prompt
    tr = generation.formula_hint("TR", ["rc", "defense_recours", "collision", "vol"])
    assert "uniquement par ces garanties : collision, vol" in tr


def test_unknown_variant_is_an_error():
    with pytest.raises(ValueError, match="unknown llm.prompt_variant"):
        generation.build_prompt(**PROMPT_ARGS, variant="other")


def test_prompt_variant_option_overrides_the_config_for_the_run(monkeypatch, tmp_path):
    monkeypatch.setitem(CONFIG["llm"], "prompt_variant", "current")
    monkeypatch.setattr(evaluate, "RESULTS_FILE", tmp_path / "eval_results.json")
    monkeypatch.setattr(evaluate, "load_cases", lambda path: [])
    monkeypatch.setattr(evaluate, "warm_up", lambda: None)
    seen = {}

    def fake_evaluate(cases, generator=None):
        seen["variant"] = CONFIG["llm"]["prompt_variant"]
        return {"metrics": {"llm_answers": 0}, "rows": []}

    monkeypatch.setattr(evaluate, "evaluate", fake_evaluate)
    evaluate.main(["--prompt-variant", "formula_hint", "--no-mlflow"])
    assert seen["variant"] == "formula_hint"
    report = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    assert report["llm_settings"]["prompt_variant"] == "formula_hint"


# --- truncated prompt check ---------------------------------------------------------

def test_full_prompt_gives_no_warning(caplog):
    prompt = "x" * 3550                                  # ~1000 tokens at 3.55 chars / token
    assert generation.warn_if_prompt_truncated(prompt, 1000, "qwen2.5:7b") is False
    assert "truncated" not in caplog.text


def test_too_few_prompt_tokens_logs_a_warning(caplog):
    prompt = "x" * 9000                                  # at least 2000 tokens expected
    with caplog.at_level("WARNING", logger="agents.policy.generation"):
        assert generation.warn_if_prompt_truncated(prompt, 1200, "qwen2.5:7b") is True
    assert "probably truncated" in caplog.text


def test_unknown_token_count_is_not_a_truncation():
    assert generation.warn_if_prompt_truncated("x" * 9000, None, "m") is False


def test_ollama_call_checks_the_prompt_token_count(fake_ollama, caplog):
    fake_ollama["prompt_eval_count"] = 10
    with caplog.at_level("WARNING", logger="agents.policy.generation"):
        assert generation.ollama_generate("Bonjour " * 500) == ANSWER   # answer still used
    assert "probably truncated" in caplog.text
