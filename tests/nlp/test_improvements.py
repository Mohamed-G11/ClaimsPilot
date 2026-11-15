
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
