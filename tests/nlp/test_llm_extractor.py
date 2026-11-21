import json

from agents.nlp.llm_extractor import extract_with_llm


def test_valid_extraction():
    def fake_generator(prompt):
        return json.dumps({
            "parts_damaged": ["hood"],
            "parts_explicitly_not_damaged": ["door"],
            "reason": "The hood is dented; the door is fine.",
        })

    result = extract_with_llm(
        "The door is fine but the hood is dented",
        generator=fake_generator,
    )

    assert result is not None
    assert result["parts_damaged"] == ["hood"]
    assert result["parts_explicitly_not_damaged"] == ["door"]


def test_invalid_part():
    result = extract_with_llm(
        "The engine is damaged",
        generator=lambda prompt: json.dumps({
            "parts_damaged": ["engine"],
            "parts_explicitly_not_damaged": [],
            "reason": "Engine damage.",
        }),
    )

    assert result is None


def test_contradictory_parts():
    result = extract_with_llm(
        "The hood is damaged",
        generator=lambda prompt: json.dumps({
            "parts_damaged": ["hood"],
            "parts_explicitly_not_damaged": ["hood"],
            "reason": "Contradictory extraction.",
        }),
    )

    assert result is None


def test_invalid_json():
    result = extract_with_llm(
        "The hood is damaged",
        generator=lambda prompt: "not valid JSON",
    )

    assert result is None


def test_generator_failure():
    def failing_generator(prompt):
        raise TimeoutError("Ollama timed out")

    result = extract_with_llm(
        "The hood is damaged",
        generator=failing_generator,
    )

    assert result is None
