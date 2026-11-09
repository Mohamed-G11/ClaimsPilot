"""Tests for the vision agent (AGENTS.md section 6: run() returns a valid result, fake model)."""
from pathlib import Path

import pytest

pytest.importorskip("yaml")
agent = pytest.importorskip("agents.vision.agent")

schemas = pytest.importorskip("claimspilot.schemas")
ClaimInput, VisionResult = schemas.ClaimInput, schemas.VisionResult
Detection = agent.Detection

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_PARTS = {"front_bumper", "rear_bumper", "door", "hood", "trunk", "fender", "headlight",
                "taillight", "windshield", "side_mirror", "wheel", "other"}


@pytest.fixture
def photo(tmp_path: Path) -> str:
    path = tmp_path / "car.jpg"
    path.write_bytes(b"not a real image, detection is mocked")
    return str(path)


def make_claim(paths: list[str]) -> ClaimInput:
    return ClaimInput(claim_id="C-001", photo_paths=paths, text="Rear bumper hit.",
                      policy_id="P-1")


# Unit tests use the original 18-class mapping (its Minor/Medium/Major hints exercise the
# whole severity rule), whatever model/mapping the agent is configured with.
ORIGINAL_MAPPING = agent.yaml.safe_load(
    (REPO_ROOT / "agents/vision/class_mapping.yaml").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def original_mapping(monkeypatch):
    cfg = {**agent._config(), "mapping": ORIGINAL_MAPPING}
    monkeypatch.setattr(agent, "_config", lambda: cfg)


def det(class_name: str, area: float = 0.05) -> Detection:
    return Detection(class_name, [10.0, 20.0, 110.0, 220.0], 0.9, area)


def severity(*detections: Detection) -> str:
    cfg = agent._config()
    return agent._severity(list(detections), cfg["mapping"], cfg["severity"])


def test_run_maps_detections_to_schema(monkeypatch, photo):
    fake = [det("Major-rear-bumper-dent", 0.15), det("backlight", 0.01)]
    monkeypatch.setattr(agent, "_detect", lambda _path: fake)

    result = agent.run(make_claim([photo]))

    assert isinstance(result, VisionResult)
    VisionResult.model_validate(result.model_dump())  # round-trip through the contract
    assert result.claim_id == "C-001"
    assert [(d.part, d.damage_type) for d in result.damages] == [
        ("rear_bumper", "dent"), ("taillight", "crack")]
    assert result.damages[0].bbox == [10.0, 20.0, 110.0, 220.0]
    assert all(0 <= d.confidence <= 1 for d in result.damages)
    assert result.severity == "severe"
    assert result.model_version


def test_all_mapped_parts_use_shared_vocabulary():
    mapping = agent._config()["mapping"]
    assert {info["part"] for info in mapping.values()} <= SHARED_PARTS


def test_missing_photo_gives_empty_result(monkeypatch):
    monkeypatch.setattr(agent, "_detect", lambda _path: pytest.fail("must not be called"))
    result = agent.run(make_claim(["does/not/exist.jpg"]))
    assert result.damages == []
    assert result.severity == "minor"


def test_unreadable_photo_does_not_crash(monkeypatch, photo):
    def broken(_path):
        raise ValueError("cannot decode image")

    monkeypatch.setattr(agent, "_detect", broken)
    result = agent.run(make_claim([photo]))
    assert result.damages == []


def test_unmapped_class_is_ignored(monkeypatch, photo):
    monkeypatch.setattr(agent, "_detect", lambda _path: [det("car")])
    assert agent.run(make_claim([photo])).damages == []


# --- severity rule (number, type and size of damages; config.yaml `severity`) ---

def test_no_damage_is_minor():
    assert severity() == "minor"


def test_small_scratch_is_minor():
    assert severity(det("scratch", 0.01)) == "minor"  # 1 (type) + 0 (size)


def test_size_matters():
    assert severity(det("dent", 0.01)) == "minor"           # 2 + 0 = 2
    assert severity(det("dent", 0.01), det("dent", 0.15)) == "moderate"  # 2 + 4 = 6


def test_type_matters():
    # same (large) size: scratch 1+2 = 3 -> minor, crack 2+2 = 4 -> moderate
    assert severity(det("scratch", 0.15)) == "minor"
    assert severity(det("headlight-damage", 0.15)) == "moderate"


def test_number_matters():
    assert severity(det("scratch", 0.05)) == "minor"           # 2
    assert severity(*[det("scratch", 0.05)] * 3) == "moderate"  # 6
    assert severity(*[det("dent", 0.15)] * 3) == "severe"       # 12


def test_class_hint_is_a_floor():
    assert severity(det("Minor-scratch", 0.01)) == "minor"
    assert severity(det("Medium-scratch", 0.01)) == "moderate"
    assert severity(det("Major-scratch", 0.01)) == "severe"


def test_run_on_real_test_image(monkeypatch):
    """Integration test with the real weights and one test image (skipped if not pulled)."""
    monkeypatch.undo()  # use the agent's real config (configured model + its mapping)
    pytest.importorskip("ultralytics")
    weights = REPO_ROOT / agent._config()["agent"]["weights"]
    images = sorted((REPO_ROOT / "data/vision/car_dent_scratch_split/test/images").glob("*.jpg"))
    if not weights.exists() or not images:
        pytest.skip("weights or test images not available (run `dvc pull`)")

    result = agent.run(make_claim([str(images[0])]))
    assert isinstance(result, VisionResult)
    assert result.severity in {"minor", "moderate", "severe"}


def test_merged_mapping_uses_shared_vocabulary():
    path = REPO_ROOT / "agents/vision/class_mapping_merged.yaml"
    if not path.exists():
        pytest.skip("merged mapping not generated (python -m agents.vision.merge_classes)")
    mapping = agent.yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(mapping) == 8
    assert {info["part"] for info in mapping.values()} <= SHARED_PARTS