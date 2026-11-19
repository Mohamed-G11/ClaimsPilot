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
    """Replace urlopen: records the JSON body sent, answers with fake["response"]."""
    fake = {"response": ANSWER, "sent": None}

    def urlopen(request, timeout):
        fake["sent"] = json.loads(request.data.decode("utf-8"))
        return io.BytesIO(json.dumps({"response": fake["response"]}).encode("utf-8"))

    monkeypatch.setattr(generation.urllib.request, "urlopen", urlopen)
    return fake


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


def test_model_option_overrides_the_config_for_the_run(monkeypatch, tmp_path):
    monkeypatch.setitem(CONFIG["llm"], "model", "model-from-config")   # restored after
    monkeypatch.setattr(evaluate, "RESULTS_FILE", tmp_path / "eval_results.json")
    monkeypatch.setattr(evaluate, "load_cases", list)              # no claim
    seen = {}

    def fake_evaluate(cases, generator=None):
        seen["model"] = CONFIG["llm"]["model"]
        return {"metrics": {"llm_answers": 1}, "rows": []}

    monkeypatch.setattr(evaluate, "evaluate", fake_evaluate)
    evaluate.main(["--model", "qwen2.5:7b", "--no-mlflow"])
    assert seen["model"] == "qwen2.5:7b"
    report = json.loads((tmp_path / "eval_results.json").read_text(encoding="utf-8"))
    assert report["generator"] == "qwen2.5:7b"
