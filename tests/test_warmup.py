"""LLM warm-up at API start: background, failure only logged (no Ollama call here)."""
import logging

from fastapi.testclient import TestClient

from agents.policy import generation
from api import main, warmup


def test_warm_up_calls_the_llm_once():
    prompts = []
    assert warmup.warm_policy_llm(prompts.append) is True
    assert prompts == [warmup.PROMPT]


def test_warm_up_failure_is_only_logged(caplog):
    def down(prompt):
        raise generation.GeneratorUnavailable("Ollama not reachable")

    with caplog.at_level(logging.WARNING, logger="api.warmup"):
        assert warmup.warm_policy_llm(down) is False
    assert "warm-up failed" in caplog.text


def test_warm_up_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("CLAIMSPILOT_WARMUP", "0")
    assert warmup.start_warmup() is None


def test_warm_up_runs_in_a_background_thread(monkeypatch):
    monkeypatch.setenv("CLAIMSPILOT_WARMUP", "1")
    calls = []
    monkeypatch.setattr(warmup, "warm_policy_llm", lambda: calls.append("warm"))
    thread = warmup.start_warmup()
    thread.join(timeout=5)
    assert thread.daemon and calls == ["warm"]


def test_api_start_launches_the_warm_up(monkeypatch):
    started = []
    monkeypatch.setattr(warmup, "start_warmup", lambda: started.append(True))
    with TestClient(main.app) as client:            # runs the lifespan (startup)
        assert client.get("/health").json() == {"status": "ok"}
    assert started == [True]
