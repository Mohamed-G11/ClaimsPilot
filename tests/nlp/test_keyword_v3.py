import pytest

from agents.nlp.agent import check_consistency, extract_damaged_parts


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Le phare arrière est cassé", ["taillight"]),
        ("Mon parebrise est fissuré", ["windshield"]),
        ("L'avant de la voiture est enfoncé", ["front_bumper"]),
        ("The door is fine but the hood is dented", ["hood"]),
        (
            "Le capot et le pare-chocs avant sont abîmés, pas le phare",
            ["front_bumper", "hood"],
        ),
    ],
)
def test_keyword_regressions(text, expected):
    assert extract_damaged_parts(text) == expected


def test_text_subset_of_vision_is_consistent():
    assert check_consistency(
        ["hood"],
        ["hood", "door"],
    ) == "consistent"
