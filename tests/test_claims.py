"""API and pipeline tests.

They never depend on which optional libraries (ultralytics, chromadb...) are
installed: the "real" agents are replaced either by fakes or by functions that
fail like a missing library would.
"""
import pytest
from fastapi.testclient import TestClient

from agents.decision import agent as decision_agent
from agents.decision import rules as decision_rules
from api import pipeline
from api.main import app
from api.pipeline import make_decision, nlp_stub, policy_stub, vision_stub
from claimspilot.schemas import ClaimInput

client = TestClient(app)

CLAIM = {
    "claim_id": "C-001",
    "photo_paths": ["photos/c001_front.jpg"],
    "text": "Le pare-chocs avant est enfoncé.",
    "policy_id": "POL-123",
}


def _unavailable(*_args):
    raise ImportError("library not installed")


@pytest.fixture
def no_real_agents(monkeypatch):
    """Same situation as CI and the light Docker image: every agent falls back to its stub."""
    for name in ("vision_real", "nlp_real", "policy_real"):
        monkeypatch.setattr(pipeline, name, _unavailable)


@pytest.fixture
def fake_real_agents(monkeypatch):
    """Every agent answers "for real" (the stubs' content, but reported as real)."""
    monkeypatch.setattr(pipeline, "vision_real", vision_stub)
    monkeypatch.setattr(pipeline, "nlp_real", nlp_stub)
    monkeypatch.setattr(pipeline, "policy_real", policy_stub)


# --- HTTP routes -----------------------------------------------------------

def test_claim_returns_a_decision(no_real_agents):
    response = client.post("/claims", json=CLAIM)
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == "C-001"
    assert body["decision"] in {"approve", "reject", "human_review"}


def test_missing_field_is_rejected():
    bad = {k: v for k, v in CLAIM.items() if k != "text"}
    response = client.post("/claims", json=bad)
    assert response.status_code == 422


def test_analyze_returns_every_agent_result(no_real_agents):
    response = client.post("/claims/analyze", json=CLAIM)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"vision", "nlp", "policy", "decision", "agents"}
    assert set(body["agents"]) == {"vision", "nlp", "policy", "decision"}


def test_stubs_are_reported_and_never_approved(no_real_agents):
    body = client.post("/claims/analyze", json=CLAIM).json()
    for name in ("vision", "nlp", "policy"):
        assert body["agents"][name].startswith("stub (ImportError")
    assert body["decision"]["decision"] == "human_review"
    assert "vision, nlp, policy" in body["decision"]["reasons"][0]


def test_real_agents_are_reported_and_can_approve(fake_real_agents):
    body = client.post("/claims/analyze", json=CLAIM).json()
    assert body["agents"]["vision"] == body["agents"]["nlp"] == body["agents"]["policy"] == "real"
    assert body["decision"]["decision"] == "approve"


def test_one_missing_agent_is_enough_for_human_review(fake_real_agents, monkeypatch):
    monkeypatch.setattr(pipeline, "policy_real", _unavailable)
    body = client.post("/claims/analyze", json=CLAIM).json()
    assert body["agents"]["vision"] == "real"
    assert body["agents"]["policy"].startswith("stub")
    assert body["decision"]["decision"] == "human_review"
    assert "policy" in body["decision"]["reasons"][0]


# --- fallback mechanism ----------------------------------------------------

def test_call_uses_the_real_agent_when_it_works():
    status = {}
    result = pipeline._call("x", lambda a: a + 1, lambda a: -1, 1, status=status)
    assert result == 2
    assert status == {"x": "real"}


def test_call_falls_back_to_the_stub_and_says_why():
    status = {}

    def broken(_a):
        raise FileNotFoundError("weights missing")

    result = pipeline._call("x", broken, lambda a: -1, 1, status=status)
    assert result == -1
    assert status["x"] == "stub (FileNotFoundError: weights missing)"


# --- decision: stub safety rule, then the decision agent, then its rules -------

def _results():
    claim = ClaimInput(**CLAIM)
    vision = vision_stub(claim)
    return claim, vision, nlp_stub(claim, vision), policy_stub(claim, vision)


def _langgraph_missing(*_args):
    raise ModuleNotFoundError("No module named 'langgraph'")


@pytest.fixture
def decision_agent_calls(monkeypatch):
    """Fake LangGraph agent: records its calls and applies Wiem's rules (no LangGraph needed)."""
    calls = []

    def fake_run(claim, vision, nlp, policy):
        calls.append(claim.claim_id)
        return decision_rules.decide(claim, vision, nlp, policy)

    monkeypatch.setattr(decision_agent, "run", fake_run)
    return calls


def test_covered_and_consistent_is_approved_by_the_decision_agent(decision_agent_calls):
    decision, how = make_decision(*_results(), stubs=[])
    assert decision_agent_calls == ["C-001"]
    assert how == "langgraph"
    assert decision.decision == "approve"
    assert decision.confidence == pytest.approx(0.82)  # min(nlp 0.9, vision 0.82, max 0.9)


def test_any_stub_goes_to_human_without_calling_the_decision_agent(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    decision, how = make_decision(claim, vision, nlp, policy, stubs=["vision", "policy"])
    assert decision_agent_calls == []
    assert how == "safety: stub used"
    assert decision.decision == "human_review"
    assert decision.confidence == 0.0
    assert "vision" in decision.reasons[0] and "policy" in decision.reasons[0]
    assert "nlp" not in decision.reasons[0]


def test_stub_wins_over_reject(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    policy.covered = False                      # invented by a stub: not a reason to reject
    decision, _ = make_decision(claim, vision, nlp, policy, stubs=["policy"])
    assert decision.decision == "human_review"


def test_uncertain_text_goes_to_human_never_approve(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    nlp.consistency = "uncertain"               # high score: only the uncertain rule fires
    decision, _ = make_decision(claim, vision, nlp, policy, stubs=[])
    assert decision.decision == "human_review"
    assert any("could not be compared" in reason for reason in decision.reasons)


def test_not_covered_is_rejected(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    policy.covered = False
    assert make_decision(claim, vision, nlp, policy, stubs=[])[0].decision == "reject"


def test_inconsistent_text_goes_to_human(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    nlp.consistency = "inconsistent"
    assert make_decision(claim, vision, nlp, policy, stubs=[])[0].decision == "human_review"


def test_severe_damage_goes_to_human(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    vision.severity = "severe"
    assert make_decision(claim, vision, nlp, policy, stubs=[])[0].decision == "human_review"


def test_unknown_coverage_goes_to_human(decision_agent_calls):
    claim, vision, nlp, policy = _results()
    policy.covered = None
    assert make_decision(claim, vision, nlp, policy, stubs=[])[0].decision == "human_review"


@pytest.mark.parametrize("change", ["none", "not_covered", "uncertain", "severe"])
def test_langgraph_missing_falls_back_to_the_same_rules(monkeypatch, change):
    claim, vision, nlp, policy = _results()
    if change == "not_covered":
        policy.covered = False
    elif change == "uncertain":
        nlp.consistency = "uncertain"
    elif change == "severe":
        vision.severity = "severe"
    with_agent = decision_rules.decide(claim, vision, nlp, policy)  # what the graph applies
    monkeypatch.setattr(decision_agent, "run", _langgraph_missing)
    decision, how = make_decision(claim, vision, nlp, policy, stubs=[])
    assert how == "rules (fallback: ModuleNotFoundError)"
    assert decision == with_agent


def test_real_langgraph_agent_matches_the_fallback(monkeypatch):
    pytest.importorskip("langgraph")
    claim, vision, nlp, policy = _results()
    decision, how = make_decision(claim, vision, nlp, policy, stubs=[])
    assert how == "langgraph"
    monkeypatch.setattr(decision_agent, "run", _langgraph_missing)
    assert make_decision(claim, vision, nlp, policy, stubs=[]) == (decision, "rules (fallback: ModuleNotFoundError)")


def test_analyze_reports_how_the_decision_was_made(fake_real_agents, decision_agent_calls,
                                                  monkeypatch):
    assert client.post("/claims/analyze", json=CLAIM).json()["agents"]["decision"] == "langgraph"
    monkeypatch.setattr(decision_agent, "run", _langgraph_missing)
    body = client.post("/claims/analyze", json=CLAIM).json()
    assert body["agents"]["decision"] == "rules (fallback: ModuleNotFoundError)"
    assert body["decision"]["decision"] == "approve"


def test_analyze_reports_the_stub_safety_rule(no_real_agents, decision_agent_calls):
    body = client.post("/claims/analyze", json=CLAIM).json()
    assert body["agents"]["decision"] == "safety: stub used"
    assert decision_agent_calls == []


def _config_missing(*_args):
    raise FileNotFoundError("agents/decision/config.yaml")


def test_rules_failing_too_goes_to_human_never_500(monkeypatch):
    monkeypatch.setattr(decision_agent, "run", _langgraph_missing)
    monkeypatch.setattr(decision_rules, "decide", _config_missing)
    decision, how = make_decision(*_results(), stubs=[])
    assert decision.decision == "human_review"
    assert decision.confidence == 0.0
    assert "both failed" in decision.reasons[0]
    assert how == "safety: decision failed (ModuleNotFoundError, FileNotFoundError)"


def test_rules_failing_too_still_answers_over_http(fake_real_agents, monkeypatch):
    monkeypatch.setattr(decision_agent, "run", _langgraph_missing)
    monkeypatch.setattr(decision_rules, "decide", _config_missing)
    response = client.post("/claims/analyze", json=CLAIM)
    assert response.status_code == 200
    assert response.json()["decision"]["decision"] == "human_review"
    assert response.json()["agents"]["decision"].startswith("safety: decision failed")
