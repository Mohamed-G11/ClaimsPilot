from fastapi.testclient import TestClient

from api.main import app
from api.pipeline import decide, nlp_stub, policy_stub, vision_stub
from claimspilot.schemas import ClaimInput

client = TestClient(app)

CLAIM = {
    "claim_id": "C-001",
    "photo_paths": ["photos/c001_front.jpg"],
    "text": "Le pare-chocs avant est enfoncé.",
    "policy_id": "POL-123",
}


def test_claim_returns_a_decision():
    response = client.post("/claims", json=CLAIM)
    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == "C-001"
    assert body["decision"] in {"approve", "reject", "human_review"}


def test_missing_field_is_rejected():
    bad = {k: v for k, v in CLAIM.items() if k != "text"}
    response = client.post("/claims", json=bad)
    assert response.status_code == 422


def _results():
    claim = ClaimInput(**CLAIM)
    vision = vision_stub(claim)
    return claim, vision, nlp_stub(claim, vision), policy_stub(claim, vision)


def test_not_covered_is_rejected():
    claim, vision, nlp, policy = _results()
    policy.covered = False
    assert decide(claim, vision, nlp, policy).decision == "reject"


def test_inconsistent_text_goes_to_human():
    claim, vision, nlp, policy = _results()
    nlp.consistency = "inconsistent"
    assert decide(claim, vision, nlp, policy).decision == "human_review"


def test_severe_damage_goes_to_human():
    claim, vision, nlp, policy = _results()
    vision.severity = "severe"
    assert decide(claim, vision, nlp, policy).decision == "human_review"


def test_all_good_and_all_real_is_approved():
    claim, vision, nlp, policy = _results()
    result = decide(claim, vision, nlp, policy, stubs=[])
    assert result.decision == "approve"
    assert result.confidence == 0.9


def test_uncertain_text_goes_to_human_never_approve():
    claim, vision, nlp, policy = _results()
    nlp.consistency, nlp.score = "uncertain", 0.0
    result = decide(claim, vision, nlp, policy)
    assert result.decision == "human_review"
    assert any("uncertain" in reason for reason in result.reasons)


def test_unknown_coverage_goes_to_human():
    claim, vision, nlp, policy = _results()
    policy.covered = None
    assert decide(claim, vision, nlp, policy).decision == "human_review"


def test_any_stub_goes_to_human_and_reasons_name_the_stubs():
    claim, vision, nlp, policy = _results()
    result = decide(claim, vision, nlp, policy, stubs=["vision", "policy"])
    assert result.decision == "human_review"
    assert "vision" in result.reasons[0] and "policy" in result.reasons[0]
    assert "nlp" not in result.reasons[0]


def test_stub_wins_over_reject():
    claim, vision, nlp, policy = _results()
    policy.covered = False                      # invented by a stub: not a reason to reject
    assert decide(claim, vision, nlp, policy, stubs=["policy"]).decision == "human_review"


def test_analyze_returns_every_agent_result():
    response = client.post("/claims/analyze", json=CLAIM)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"vision", "nlp", "policy", "decision", "agents"}
    assert set(body["agents"]) == {"vision", "nlp", "policy", "decision"}
