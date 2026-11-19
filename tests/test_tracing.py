"""Langfuse tracing with a FAKE client: what is traced, and that tracing never breaks
a claim. Nothing is sent to Langfuse (see tests/conftest.py)."""
from contextlib import contextmanager, nullcontext

import pytest

from agents.policy import generation
from api import pipeline, tracing
from tests.test_pipeline_e2e import COLLISION, analyze, photo, real_agents  # noqa: F401

TRACE_ID = "a" * 32


class FakeObservation:
    def __init__(self, record):
        self.record = record
        self.trace_id = TRACE_ID

    def update(self, **fields):
        self.record["updates"].update(fields)


class FakeLangfuse:
    """Records every observation: name, type, start fields, updates, parent."""

    def __init__(self):
        self.observations, self._stack = [], []

    @contextmanager
    def start_as_current_observation(self, name, as_type="span", **fields):
        record = {"name": name, "as_type": as_type, "fields": fields, "updates": {},
                  "parent": self._stack[-1]["name"] if self._stack else None}
        self.observations.append(record)
        self._stack.append(record)
        try:
            yield FakeObservation(record)
        finally:
            self._stack.pop()

    def named(self, name):
        return [o for o in self.observations if o["name"] == name]


@pytest.fixture
def fake_langfuse(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(tracing, "client", lambda: fake)
    monkeypatch.setattr(tracing, "_propagate", lambda *args: nullcontext())
    return fake


# --- tracing off (no keys) ---------------------------------------------------------

def test_tracing_is_off_without_keys():
    assert tracing.enabled() is False
    assert tracing.client() is None


def test_kill_switch_wins_over_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("CLAIMSPILOT_TRACING", "0")
    assert tracing.enabled() is False


def test_without_tracing_the_claim_has_no_trace_id(real_agents, photo):  # noqa: F811
    body = analyze(photo, COLLISION)
    assert body["decision"]["trace_id"] is None
    assert body["decision"]["decision"] == "approve"


def test_no_op_observation_never_raises():
    with tracing.observe("x") as step:
        step.update(output="ignored")
    assert step.trace_id is None


# --- tracing on (fake client) ----------------------------------------------------

def test_one_trace_per_claim_with_one_observation_per_step(fake_langfuse, real_agents,  # noqa: F811
                                                            photo):  # noqa: F811
    real_agents["llm"] = lambda prompt: "Décision : COUVERT. Collision garantie [AXA-015]."
    body = analyze(photo, COLLISION)

    root = fake_langfuse.named("claim")[0]
    assert root["parent"] is None
    assert root["fields"]["input"]["claim_id"] == "E2E-1"
    assert root["updates"]["output"] == {"decision": "approve",
                                         "confidence": body["decision"]["confidence"],
                                         "status": body["agents"]["decision"]}
    for name in ("vision", "nlp", "policy", "decision"):
        assert fake_langfuse.named(name)[0]["parent"] == "claim"
    retrievals = fake_langfuse.named("policy retrieval")
    assert retrievals and all(r["parent"] == "policy" for r in retrievals)
    assert all(r["as_type"] == "retriever" for r in retrievals)
    llm = fake_langfuse.named("policy LLM call")[0]
    assert llm["as_type"] == "generation" and llm["parent"] == "policy"
    assert llm["fields"]["model"] and "Collision sur un parking" in llm["fields"]["input"]
    assert llm["updates"]["output"].startswith("Décision : COUVERT")
    decision = fake_langfuse.named("decision")[0]["updates"]["output"]
    assert decision["status"] == body["agents"]["decision"]
    assert body["decision"]["trace_id"] == TRACE_ID          # also returned to the caller


def test_ollama_token_usage_is_recorded(fake_langfuse, monkeypatch):
    monkeypatch.setattr(generation, "default_generator", lambda: generation.ollama_generate)
    monkeypatch.setattr(generation, "ollama_call", lambda prompt: generation.OllamaAnswer(
        text="Décision : COUVERT.", model="qwen2.5:7b", input_tokens=812, output_tokens=64))
    assert pipeline._traced_generator("prompt") == "Décision : COUVERT."
    llm = fake_langfuse.named("policy LLM call")[0]
    assert llm["updates"]["usage_details"] == {"input": 812, "output": 64}


def test_llm_unavailable_is_marked_and_the_template_is_used(fake_langfuse, real_agents,  # noqa: F811
                                                            photo):  # noqa: F811
    body = analyze(photo, COLLISION)                   # real_agents' llm = no_generator
    assert body["policy"]["model_version"].endswith("+template")
    assert fake_langfuse.named("policy LLM call")[0]["updates"]["level"] == "WARNING"


def test_a_broken_langfuse_never_breaks_a_claim(monkeypatch, real_agents, photo):  # noqa: F811
    class Broken:
        def start_as_current_observation(self, **fields):
            raise RuntimeError("Langfuse is down")

    monkeypatch.setattr(tracing, "client", lambda: Broken())
    body = analyze(photo, COLLISION)
    assert body["decision"]["decision"] == "approve"
    assert body["decision"]["trace_id"] is None


def test_errors_inside_a_step_are_re_raised(fake_langfuse):
    with pytest.raises(ValueError), tracing.observe("step"):
        raise ValueError("agent bug")
    assert fake_langfuse.named("step")[0]["updates"]["level"] == "ERROR"
