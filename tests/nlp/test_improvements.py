
import pytest

from agents.nlp.agent import (
    extract_damaged_parts,
    check_consistency,
)


def test_french_negation():
    text = (
        "Le capot est abîmé, mais la portière "
        "n'a subi aucun dommage."
    )
    assert extract_damaged_parts(text) == ["hood"]


def test_english_negation():
    text = (
        "The front bumper is damaged, "
        "but the windshield is not damaged."
    )
    assert extract_damaged_parts(text) == ["front_bumper"]


def test_french_accents():
    text = "Le rétroviseur gauche est cassé."
    assert extract_damaged_parts(text) == ["side_mirror"]


def test_multiple_parts():
    text = "The rear bumper and the door are damaged."
    assert set(extract_damaged_parts(text)) == {
        "rear_bumper", "door"
    }


@pytest.mark.parametrize(
    ("described", "vision", "expected"),
    [
        (["hood"], ["hood"], "consistent"),
        (["hood"], ["wheel"], "inconsistent"),
        ([], ["hood"], "uncertain"),
    ],
)
def test_consistency_basic_cases(described, vision, expected):
    assert check_consistency(described, vision) == expected

def test_configurable_thresholds():
    described = ["hood", "door", "wheel"]
    vision = ["hood", "door"]

    assert check_consistency(
        described, vision
    ) == "uncertain"

    assert check_consistency(
        described,
        vision,
        consistent_threshold=0.6,
    ) == "consistent"


def test_low_overlap_threshold():
    described = ["hood", "door", "wheel"]
    vision = ["hood", "headlight", "trunk"]

    assert check_consistency(
        described, vision
    ) == "inconsistent"


def test_invalid_thresholds():
    with pytest.raises(ValueError):
        check_consistency(
            ["hood"],
            ["hood"],
            consistent_threshold=0.2,
            inconsistent_threshold=0.8,
        )
def test_front_light_synonym():
    from agents.nlp.agent import extract_damaged_parts

    text = (
        "After an accident in a parking lot, "
        "the front light was damaged."
    )

    assert extract_damaged_parts(text) == ["headlight"]