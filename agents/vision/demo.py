"""Run the vision agent on sample photos and save the VisionResult as JSON.

The JSON files in agents/vision/examples/ are real outputs that teammates (NLP, policy,
decision agents) can use as test inputs without installing the vision stack.

Usage (from the repo root, weights pulled with `dvc pull`):
    python -m agents.vision.demo                      # 3 images from the test split
    python -m agents.vision.demo path/a.jpg path/b.jpg
"""
import argparse
from pathlib import Path

from agents.vision import agent

# isort: split
from claimspilot.schemas import ClaimInput

TEST_IMAGES = Path("data/vision/car_dent_scratch_split/test/images")
OUT_DIR = Path("agents/vision/examples")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("photos", nargs="*", help="photo paths (default: 3 test images)")
    args = parser.parse_args()
    photos = args.photos or [str(p) for p in sorted(TEST_IMAGES.glob("*.jpg"))[::100][:3]]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for i, photo in enumerate(photos, start=1):
        claim = ClaimInput(claim_id=f"DEMO-{i:03d}", photo_paths=[photo],
                           text="(demo claim)", policy_id="P-DEMO")
        result = agent.run(claim)
        out = OUT_DIR / f"vision_result_{i:03d}.json"
        out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        parts = ", ".join(f"{d.part}/{d.damage_type} ({d.confidence:.2f})" for d in result.damages)
        print(f"{claim.claim_id} {Path(photo).name}\n  severity={result.severity} "
              f"damages=[{parts or 'none'}]\n  -> {out}")


if __name__ == "__main__":
    main()