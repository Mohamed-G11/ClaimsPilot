"""Tests for the vision agent (AGENTS.md section 6: tiny sample, output matches schema)."""
from pathlib import Path

import pytest

pytest.importorskip("yaml")
agent = pytest.importorskip("agents.vision.agent")

schemas = pytest.importorskip("claimspilot.schemas")
ClaimInput, VisionResult = schemas.ClaimInput, schemas.VisionResult

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def photo(tmp_path: Path) -> str:
    path = tmp_path / "car.jpg"
    path.write_bytes(b"not a real image, detection is mocked")
    return str(path)


def make_claim(paths: list[str]) -> ClaimInput:
    return ClaimInput(claim_id="C-001", photo_paths=paths, text="Rear bumper hit.",
                      policy_id="P-1")


def test_run_maps_detections_to_schema(monkeypatch, photo):
    fake = [
        ("Major-rear-bumper-dent", [10.0, 20.0, 110.0, 220.0], 0.91),
        ("backlight", [5.0, 5.0, 50.0, 40.0], 0.55),
    ]
    monkeypatch.setattr(agent, "_detect", lambda _path: fake)

    result = agent.run(make_claim([photo]))

    assert isinstance(result, VisionResult)
    VisionResult.model_validate(result.model_dump())  # round-trip through the contract
    assert result.claim_id == "C-001"
    assert [(d.part, d.damage_type) for d in result.damages] == [
        ("rear_bumper", "dent"), ("tail_light", "crack")]
    assert result.damages[0].bbox == [10.0, 20.0, 110.0, 220.0]
    assert all(0 <= d.confidence <= 1 for d in result.damages)
    assert result.severity == "severe"  # "Major-" hint
    assert result.model_version


def test_missing_photo_gives_empty_result(monkeypatch):
    monkeypatch.setattr(agent, "_detect", lambda _path: pytest.fail("must not be called"))
    result = agent.run(make_claim(["does/not/exist.jpg"]))
    assert result.damages == []
    assert result.severity == "minor"


def test_unmapped_class_is_ignored(monkeypatch, photo):
    monkeypatch.setattr(agent, "_detect", lambda _path: [("car", [0, 0, 1, 1], 0.9)])
    assert agent.run(make_claim([photo])).damages == []


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        ([], "minor"),
        (["Minor-scratch"], "minor"),
        (["Medium-scratch"], "moderate"),
        (["scratch", "dent", "headlight-damage"], "moderate"),
        (["scratch"] * 5, "severe"),
    ],
)
def test_severity_rule(classes, expected):
    assert agent._severity(classes, agent._config()["mapping"]) == expected


def test_run_on_real_test_image():
    """Integration test with the real weights and one test image (skipped if not pulled)."""
    pytest.importorskip("ultralytics")
    weights = REPO_ROOT / "models/vision/yolov8n_baseline.pt"
    images = sorted((REPO_ROOT / "data/vision/car_dent_scratch_split/test/images").glob("*.jpg"))
    if not weights.exists() or not images:
        pytest.skip("weights or test images not available (run `dvc pull`)")

    result = agent.run(make_claim([str(images[0])]))
    assert isinstance(result, VisionResult)
    assert result.severity in {"minor", "moderate", "severe"}