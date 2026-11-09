"""Vision agent: detect car damages on claim photos with YOLOv8.

Contract (AGENTS.md section 4): run(claim: ClaimInput) -> VisionResult.
Runs on CPU. Config: agents/vision/config.yaml (sections `agent` and `severity`),
overridable with VISION_CONFIG / VISION_WEIGHTS env vars.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import yaml

# isort: split
from claimspilot.schemas import ClaimInput, Damage, VisionResult

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.getenv("VISION_CONFIG", "agents/vision/config.yaml"))
SEVERITY_ORDER = ["minor", "moderate", "severe"]


class Detection(NamedTuple):
    """A raw YOLO detection, before mapping to the shared Damage schema."""

    class_name: str        # dataset class, e.g. "Major-rear-bumper-dent"
    bbox: list[float]      # [x1, y1, x2, y2] in pixels
    confidence: float      # 0..1
    area_ratio: float      # box area / image area (0..1), used by the severity rule


@lru_cache(maxsize=1)
def _config() -> dict:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    # The model's classes decide the mapping: agent.class_mapping (e.g. merged classes)
    # if set, else the original 18-class mapping.
    mapping_path = cfg["agent"].get("class_mapping", cfg["class_mapping"])
    mapping = yaml.safe_load(Path(mapping_path).read_text(encoding="utf-8"))
    return {"agent": cfg["agent"], "severity": cfg["severity"], "mapping": mapping}


@lru_cache(maxsize=1)
def _model():
    """Load the YOLO weights once (lazy import: ultralytics is only needed here)."""
    from ultralytics import YOLO

    weights = Path(os.getenv("VISION_WEIGHTS", _config()["agent"]["weights"]))
    if not weights.exists():
        raise FileNotFoundError(f"Vision weights not found: {weights} (run `dvc pull`)")
    return YOLO(str(weights))


def _detect(photo_path: str) -> list[Detection]:
    """Run YOLO on one photo and return raw detections."""
    acfg = _config()["agent"]
    model = _model()
    result = model.predict(photo_path, conf=acfg["conf"], iou=acfg["iou"],
                           imgsz=acfg["imgsz"], device="cpu", verbose=False)[0]
    boxes = result.boxes
    height, width = result.orig_shape
    detections = []
    for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(),
                               boxes.cls.tolist(), strict=True):
        x1, y1, x2, y2 = xyxy
        area_ratio = max(0.0, (x2 - x1) * (y2 - y1)) / float(width * height)
        detections.append(Detection(model.names[int(cls)], [round(v, 1) for v in xyxy],
                                    round(float(conf), 4), round(area_ratio, 4)))
    return detections


def _damage_points(det: Detection, info: dict, scfg: dict) -> int:
    """Points of one damage: type + size + class hint (see config.yaml `severity`)."""
    points = scfg["type_points"].get(info["damage_type"], scfg["default_type_points"])
    points += next(b["points"] for b in scfg["size_points"] if det.area_ratio <= b["max_area"])
    if info["severity_hint"]:
        points += scfg["hint_points"][info["severity_hint"]]
    return points


def _severity(detections: list[Detection], mapping: dict, scfg: dict) -> str:
    """Claim severity from the number, type and size of damages (config.yaml `severity`).

    Each damage scores type points (scratch < dent/crack < glass_shatter) + size points
    (box area / image area) + hint points (Minor/Medium/Major in the class name).
    The claim score is the sum over all damages, so more damages -> more severe.
    With `hint_floor`, the result is never below the worst hint (Major -> severe).
    No damage found -> "minor" (the decision agent also sees the empty list).
    """
    infos = [mapping[d.class_name] for d in detections]
    score = sum(_damage_points(d, i, scfg) for d, i in zip(detections, infos, strict=True))
    thresholds = scfg["thresholds"]
    level = 2 if score >= thresholds["severe"] else 1 if score >= thresholds["moderate"] else 0
    if scfg.get("hint_floor"):
        hints = [SEVERITY_ORDER.index(i["severity_hint"]) for i in infos if i["severity_hint"]]
        level = max([level, *hints])
    return SEVERITY_ORDER[level]


def run(claim: ClaimInput) -> VisionResult:
    cfg = _config()
    mapping = cfg["mapping"]
    damages: list[Damage] = []
    kept: list[Detection] = []

    for photo in claim.photo_paths:
        if not Path(photo).is_file():
            logger.warning("claim %s: photo not found, skipped: %s", claim.claim_id, photo)
            continue
        try:
            detections = _detect(photo)
        except Exception:  # unreadable/corrupt image must not crash the whole claim
            logger.exception("claim %s: detection failed on %s", claim.claim_id, photo)
            continue
        for det in detections:
            if det.class_name not in mapping:
                logger.warning("claim %s: unmapped class %r ignored", claim.claim_id,
                               det.class_name)
                continue
            info = mapping[det.class_name]
            damages.append(Damage(part=info["part"], damage_type=info["damage_type"],
                                  bbox=det.bbox, confidence=det.confidence))
            kept.append(det)

    return VisionResult(
        claim_id=claim.claim_id,
        damages=damages,
        severity=_severity(kept, mapping, cfg["severity"]),
        model_version=cfg["agent"]["model_version"],
    )