import pytest
from pydantic import ValidationError

from claimspilot.schemas import Damage, Decision, VisionResult


def test_valid_vision_result():
    result = VisionResult(
        claim_id="C1",
        damages=[Damage(part="door", damage_type="dent", bbox=[0, 0, 10, 10], confidence=0.9)],
        severity="moderate",
        model_version="yolov8n-e30",
    )
    assert result.damages[0].part == "door"


def test_invalid_severity_is_rejected():
    with pytest.raises(ValidationError):
        VisionResult(claim_id="C1", damages=[], severity="very bad", model_version="x")


def test_confidence_must_be_between_0_and_1():
    with pytest.raises(ValidationError):
        Decision(claim_id="C1", decision="approve", confidence=1.5, reasons=[])