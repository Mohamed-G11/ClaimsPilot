from unittest.mock import patch

from agents.nlp import agent
from claimspilot.schemas import ClaimInput, Damage, VisionResult


def make_inputs():
    claim = ClaimInput(
        claim_id="TEST-001",
        text="The door is fine but the hood is dented",
        photo_paths=[],
        policy_id="TEST-POLICY",
        language="en",
    )

    vision = VisionResult(
        claim_id="TEST-001",
        damages=[
            Damage(
                part="hood",
                damage_type="dent",
                bbox=[0, 0, 10, 10],
                confidence=0.95,
            )
        ],
        severity="minor",
        model_version="test-vision",
    )

    return claim, vision


def test_llm_success():
    claim, vision = make_inputs()

    with patch(
        "agents.nlp.llm_extractor.extract_with_llm",
        return_value={
            "parts_damaged": ["hood"],
            "parts_explicitly_not_damaged": ["door"],
            "reason": "Only the hood is damaged.",
        },
    ):
        result = agent.run(claim, vision, method="llm")

    assert result.described_parts == ["hood"]
    assert result.consistency == "consistent"
    from agents.nlp.llm_extractor import load_config
    assert result.model_version == f"nlp-llm-{load_config()['model']}"


def test_llm_fallback():
    claim, vision = make_inputs()

    with patch(
        "agents.nlp.llm_extractor.extract_with_llm",
        return_value=None,
    ):
        result = agent.run(claim, vision, method="llm")

    assert result.described_parts == ["hood"]
    assert result.consistency == "consistent"
    assert result.model_version == "nlp-keywords-v3"


def test_invalid_method():
    claim, vision = make_inputs()

    try:
        agent.run(claim, vision, method="invalid")
    except ValueError:
        return

    raise AssertionError("Invalid method should raise ValueError")
