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