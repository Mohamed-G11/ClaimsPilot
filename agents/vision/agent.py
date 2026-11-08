"""Vision agent: detect car damages on claim photos with YOLOv8.

Contract (AGENTS.md section 4): run(claim: ClaimInput) -> VisionResult.
Runs on CPU. Config: agents/vision/config.yaml (section `agent`), overridable with
VISION_CONFIG / VISION_WEIGHTS env vars.
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

import yaml

# isort: split
from claimspilot.schemas import ClaimInput, Damage, VisionResult

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.getenv("VISION_CONFIG", "agents/vision/config.yaml"))
SEVERITY_ORDER = ["minor", "moderate", "severe"]

# A detection before mapping: (dataset class name, [x1, y1, x2, y2] in pixels, confidence)
Detection = tuple[str, list[float], float]


@lru_cache(maxsize=1)
def _config() -> dict:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    mapping = yaml.safe_load(Path(cfg["class_mapping"]).read_text(encoding="utf-8"))
    return {"agent": cfg["agent"], "mapping": mapping}


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
    return [
        (model.names[int(cls)], [round(v, 1) for v in xyxy], round(float(conf), 4))
        for xyxy, conf, cls in zip(boxes.xyxy.tolist(), boxes.conf.tolist(),
                                   boxes.cls.tolist(), strict=True)
    ]


def _severity(class_names: list[str], mapping: dict) -> str:
    """Provisional sprint-1 rule (refined in week 2).

    Start from the worst severity hint encoded in the class names (Minor/Medium/Major),
    then escalate with the number of damages: >= 3 damages -> at least moderate,
    >= 5 -> severe. No damage found -> "minor" (the decision agent sees an empty list).
    """
    hints = [mapping[c]["severity_hint"] for c in class_names if mapping[c]["severity_hint"]]
    level = max((SEVERITY_ORDER.index(h) for h in hints), default=0)
    if len(class_names) >= 5:
        level = 2
    elif len(class_names) >= 3:
        level = max(level, 1)
    return SEVERITY_ORDER[level]


def run(claim: ClaimInput) -> VisionResult:
    cfg = _config()
    mapping = cfg["mapping"]
    damages: list[Damage] = []
    kept_classes: list[str] = []

    for photo in claim.photo_paths:
        if not Path(photo).is_file():
            logger.warning("claim %s: photo not found, skipped: %s", claim.claim_id, photo)
            continue
        try:
            detections = _detect(photo)
        except Exception:  # unreadable/corrupt image must not crash the whole claim
            logger.exception("claim %s: detection failed on %s", claim.claim_id, photo)
            continue
        for class_name, bbox, conf in detections:
            if class_name not in mapping:
                logger.warning("claim %s: unmapped class %r ignored", claim.claim_id, class_name)
                continue
            damages.append(Damage(part=mapping[class_name]["part"],
                                  damage_type=mapping[class_name]["damage_type"],
                                  bbox=bbox, confidence=conf))
            kept_classes.append(class_name)

    return VisionResult(
        claim_id=claim.claim_id,
        damages=damages,
        severity=_severity(kept_classes, mapping),
        model_version=cfg["agent"]["model_version"],
    )