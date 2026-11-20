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
            answer = {"response": fake["response"], "done_reason": fake["done_reason"]}
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
    monkeypatch.setattr(evaluate, "load_cases", list)              # no claim
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
