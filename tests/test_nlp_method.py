"""The API passes NLP_METHOD (keywords | llm, default llm) to Hend's NLP agent."""
import pytest

from agents.nlp import agent as nlp_agent
from api import pipeline
from claimspilot.schemas import ClaimInput, VisionResult


@pytest.fixture
def seen(monkeypatch):
    calls = []

    def fake_run(claim, vision, method="keywords"):
        calls.append(method)
        return pipeline.nlp_stub(claim, vision)

    monkeypatch.setattr(nlp_agent, "run", fake_run)
    return calls


def _inputs():
    claim = ClaimInput(claim_id="C1", photo_paths=[], text="porte endomage", policy_id="AXA-TR")
    vision = VisionResult(claim_id="C1", damages=[], severity="minor", model_version="t")
    return claim, vision


def test_default_is_llm(monkeypatch, seen):
    monkeypatch.delenv("NLP_METHOD", raising=False)
    pipeline.nlp_real(*_inputs())
    assert seen == ["llm"]


@pytest.mark.parametrize("value, expected", [("keywords", "keywords"), ("LLM", "llm"), ("", "llm")])
def test_env_value_is_passed(monkeypatch, seen, value, expected):
    monkeypatch.setenv("NLP_METHOD", value)
    pipeline.nlp_real(*_inputs())
    assert seen == [expected]


def test_unknown_value_raises(monkeypatch, seen):
    monkeypatch.setenv("NLP_METHOD", "magic")
    with pytest.raises(ValueError):
        pipeline.nlp_real(*_inputs())
    assert seen == []
