
from agents.nlp.agent import (
    analyze_claim,
    check_consistency,
    extract_damaged_parts,
)


def test_french_extraction():
    result = extract_damaged_parts("Le pare-chocs avant est rayé.")
    assert result == ["front_bumper"]


def test_english_extraction():
    result = extract_damaged_parts("My windshield is broken.")
    assert result == ["windshield"]


def test_consistent_claim():
    result = check_consistency(
        ["front_bumper"], ["front_bumper"]
    )
    assert result == "consistent"


def test_inconsistent_claim():
    result = check_consistency(
        ["front_bumper"], ["rear_bumper"]
    )
    assert result == "inconsistent"


def test_uncertain_claim():
    result = check_consistency(
        ["front_bumper"], []
    )
    assert result == "uncertain"


def test_complete_workflow():
    result = analyze_claim(
        "La portière est rayée.",
        ["door"]
    )
    assert result == {
        "described_parts": ["door"],
        "consistency": "consistent",
    }

import json
from pathlib import Path

import pytest

from agents.nlp.agent import run
from claimspilot.schemas import ClaimInput, NLPResult, VisionResult


@pytest.mark.parametrize(
    ("number", "description", "expected_parts", "expected_status"),
    [
        ("001", "Ma voiture est abîmée.", [], "uncertain"),
        ("002", "My headlight is broken.", ["headlight"], "consistent"),
        (
            "003",
            "Le pare-chocs arri\u00e8re est ab\u00eem\u00e9.",
            ["rear_bumper"],
            "consistent",
        ),
    ],
)
def test_run_with_vision_examples(
    number, description, expected_parts, expected_status
):
    path = (
        Path(__file__).resolve().parents[2]
        / "agents"
        / "vision"
        / "examples"
        / f"vision_result_{number}.json"
    )

    with path.open(encoding="utf-8") as file:
        vision = VisionResult.model_validate(json.load(file))

    claim = ClaimInput(
        claim_id=vision.claim_id,
        photo_paths=[],
        text=description,
        policy_id="TEST-001",
        language="en" if number == "002" else "fr",
    )

    result = run(claim, vision)

    assert isinstance(result, NLPResult)
    assert result.claim_id == vision.claim_id
    assert result.described_parts == expected_parts
    assert result.consistency == expected_status
    assert 0 <= result.score <= 1
    assert result.model_version

def test_consistency_edge_cases():
    from agents.nlp.agent import check_consistency

    assert check_consistency(
        ["headlight", "door"], ["headlight"]
    ) == "uncertain"

    assert check_consistency(
        ["headlight"], ["rear_bumper"]
    ) == "inconsistent"

    assert check_consistency(
        ["headlight"], ["headlight", "other"]
    ) == "consistent"

    assert check_consistency([], ["headlight"]) == "uncertain"

    assert check_consistency(
        ["hood", "wheel"], ["hood", "wheel"]
    ) == "consistent"
