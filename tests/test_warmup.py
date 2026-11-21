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
        assert client.get("/health").json()["status"] == "ok"
    assert started == [True]


# --- warm-up status, /health and /ready ------------------------------------------

def set_states(monkeypatch, **states):
    for step in warmup.STEPS:
        monkeypatch.setitem(warmup._status, step, states.get(step, "done"))


def test_ready_is_503_while_a_warm_up_runs_and_health_stays_200(monkeypatch):
    set_states(monkeypatch, llm="running", vision="pending")
    client = TestClient(main.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["warmup"]["llm"] == "running"
    ready = client.get("/ready")
    assert ready.status_code == 503 and ready.json()["ready"] is False


def test_ready_is_200_when_every_warm_up_is_done(monkeypatch):
    set_states(monkeypatch)
    response = TestClient(main.app).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "warmup": dict.fromkeys(warmup.STEPS, "done"),
                               "failed": []}


def test_a_failed_warm_up_is_finished_and_listed(monkeypatch):
    set_states(monkeypatch, llm="failed")                  # e.g. Ollama not reachable
    body = TestClient(main.app).get("/ready").json()
    assert body["ready"] is True and body["failed"] == ["llm"]


def test_steps_record_running_then_done_or_failed(monkeypatch):
    set_states(monkeypatch, vision="pending")
    seen = []

    def warm():
        seen.append(warmup.status()["vision"])
        return False

    assert warmup._run_step("vision", warm) is False
    assert seen == ["running"] and warmup.status()["vision"] == "failed"


def test_turned_off_warm_up_is_ready(monkeypatch):
    set_states(monkeypatch, llm="pending")
    monkeypatch.setenv("CLAIMSPILOT_WARMUP", "0")
    warmup.start_warmup()
    assert set(warmup.status().values()) == {"off"} and warmup.is_ready()
