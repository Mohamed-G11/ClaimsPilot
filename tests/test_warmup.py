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
    assert warmup.start_warmup() == []


def test_warm_up_runs_in_background_threads(monkeypatch):
    monkeypatch.setenv("CLAIMSPILOT_WARMUP", "1")
    calls = []
    monkeypatch.setattr(warmup, "warm_policy_llm", lambda: calls.append("llm"))
    monkeypatch.setattr(warmup, "warm_agents", lambda: calls.append("agents"))
    threads = warmup.start_warmup()
    for thread in threads:
        thread.join(timeout=5)
    assert all(t.daemon for t in threads) and sorted(calls) == ["agents", "llm"]


def test_agent_warm_ups_never_raise_and_report_each_step(monkeypatch, caplog):
    import builtins

    real_import = builtins.__import__

    def no_heavy_libraries(name, *args, **kwargs):
        if name in ("cv2", "sentence_transformers", "chromadb", "langgraph.graph"):
            raise ImportError(f"{name} not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_heavy_libraries)
    monkeypatch.setattr("agents.decision.agent._default_graph",
                        lambda: (_ for _ in ()).throw(ImportError("langgraph")))
    with caplog.at_level(logging.WARNING, logger="api.warmup"):
        result = warmup.warm_agents()
    assert result == {"vision": False, "retrieval": False, "decision": False}
    for step in ("vision", "retrieval", "decision graph"):
        assert f"{step} warm-up failed" in caplog.text


def test_agent_warm_ups_call_the_public_entry_points(monkeypatch):
    from agents.decision import agent as decision_agent
    from agents.policy import agent as policy_agent

    calls = []
    monkeypatch.setattr(policy_agent, "retrieve", lambda *args: calls.append(("retrieve", args)))
    monkeypatch.setattr(decision_agent, "run", lambda *args: calls.append(("decision", None)))
    assert warmup.warm_retrieval() and warmup.warm_decision()
    assert calls[0][0] == "retrieve" and calls[0][1][1] == "AXA" and calls[1][0] == "decision"


def test_api_start_launches_the_warm_up(monkeypatch):
    started = []
    monkeypatch.setattr(warmup, "start_warmup", lambda: started.append(True))
    with TestClient(main.app) as client:            # runs the lifespan (startup)
        assert client.get("/health").json() == {"status": "ok"}
    assert started == [True]
