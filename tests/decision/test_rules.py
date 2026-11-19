"""Decision rules (no LangGraph, no model): one test per rule + the example VisionResults."""
from pathlib import Path

import pytest

pytest.importorskip("yaml")
rules = pytest.importorskip("agents.decision.rules")
stubs = pytest.importorskip("agents.decision.stubs")
schemas = pytest.importorskip("claimspilot.schemas")

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "agents/vision/examples"
CLAIM = schemas.ClaimInput(claim_id="C-1", photo_paths=["car.jpg"], text="Rear bumper hit.",
                           policy_id="P-1")


def vision(*confidences: float, severity: str = "moderate"):
    damages = [schemas.Damage(part="rear_bumper", damage_type="dent", bbox=[0, 0, 10, 10],
                              confidence=c) for c in confidences]
    return schemas.VisionResult(claim_id="C-1", damages=damages, severity=severity,
                                model_version="test")


def nlp(consistency: str = "consistent", score: float = 0.9):
    return schemas.NLPResult(claim_id="C-1", described_parts=["rear_bumper"],
                             consistency=consistency, score=score, model_version="test")


def policy(covered: bool | None = True):
    return schemas.PolicyResult(claim_id="C-1", covered=covered, answer="art. 4",
                                clauses=[], model_version="test")


def decide(v=None, n=None, p=None, cfg=None):
    return rules.decide(CLAIM, v or vision(0.8), n or nlp(), p or policy(), cfg)


def test_all_good_is_approved_with_reasons():
    d = decide()
    assert isinstance(d, schemas.Decision)
    assert d.decision == "approve"
    assert d.confidence == pytest.approx(0.8)  # min(nlp 0.9, vision 0.8, max 0.9)
    assert any(r.startswith("APPROVE") for r in d.reasons)
    assert any(r.startswith("vision:") for r in d.reasons)


def test_not_covered_is_rejected_first():
    d = decide(n=nlp("inconsistent"), p=policy(False))  # reject wins over review
    assert d.decision == "reject"
    assert any("not covered" in r for r in d.reasons)


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        ({"p": policy(None)}, "could not decide the coverage"),
        ({"n": nlp("inconsistent")}, "does not match"),
        ({"n": nlp(score=0.3)}, "low text/photo consistency score"),
        ({"v": vision(0.8, severity="severe")}, "severe damage"),
        ({"v": vision()}, "no damage detected"),
        ({"v": vision(0.2, 0.25)}, "low vision confidence"),
    ],
)
def test_review_rules(kwargs, expected_reason):
    d = decide(**kwargs)
    assert d.decision == "human_review"
    assert any(r.startswith("HUMAN REVIEW") and expected_reason in r for r in d.reasons)


def test_uncertain_text_is_configurable():
    assert decide(n=nlp("uncertain")).decision == "approve"  # default: off
    cfg = rules.load_config()
    strict = {**cfg, "rules": {**cfg["rules"], "review_if_uncertain": True}}
    assert decide(n=nlp("uncertain"), cfg=strict).decision == "human_review"


def test_thresholds_are_configurable():
    cfg = rules.load_config()
    lenient = {**cfg, "rules": {**cfg["rules"], "min_vision_confidence": 0.1,
                                 "review_severities": []}}
    assert decide(v=vision(0.2, severity="severe"), cfg=lenient).decision == "approve"


@pytest.mark.parametrize(
    ("example", "expected"),
    [
        ("vision_result_001.json", "human_review"),  # no damage found
        ("vision_result_002.json", "human_review"),  # headlight crack, confidence 0.28
        ("vision_result_003.json", "approve"),       # rear bumper dent, confidence 0.40
    ],
)
def test_real_vision_examples(example, expected):
    if not (EXAMPLES / example).exists():
        pytest.skip("vision examples not available")
    v = stubs.vision_stub(CLAIM, example)
    d = rules.decide(CLAIM, v, stubs.nlp_stub(CLAIM, v), stubs.policy_stub(CLAIM, v))
    assert d.decision == expected
    assert d.claim_id == "C-1"