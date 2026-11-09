"""Train a YOLOv8 model on CPU and log everything to the shared MLflow (DagsHub).

Usage (from the repo root, venv activated, .env filled with DagsHub credentials):
    python -m agents.vision.train                                   # baseline (config.yaml)
    python -m agents.vision.train --smoke                           # 1 epoch on 10% of train
    python -m agents.vision.train --epochs 30 --name yolov8n-e30    # second training
    python -m agents.vision.train --merged --epochs 30 --name yolov8n-merged-e30

Env vars (read from .env):
    MLFLOW_TRACKING_URI   shared DagsHub MLflow (AGENTS.md section 6)
    VISION_CONFIG         default agents/vision/config.yaml
"""
import argparse
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import mlflow
import pandas as pd
import yaml
from dotenv import load_dotenv
from ultralytics import YOLO, settings

load_dotenv()  # MLFLOW_TRACKING_URI + DagsHub credentials from .env (AGENTS.md section 6)

CONFIG_PATH = Path(os.getenv("VISION_CONFIG", "agents/vision/config.yaml"))


def git_commit() -> str:
    """Current commit hash, suffixed with -dirty if there are uncommitted changes."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "agents"], text=True)
        return f"{sha}-dirty" if dirty.strip() else sha
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def data_version(data_dir: Path) -> str:
    """DVC md5 of the dataset if it is DVC-tracked, else a content hash of the labels."""
    dvc_file = data_dir.with_name(data_dir.name + ".dvc")
    if dvc_file.exists():
        outs = yaml.safe_load(dvc_file.read_text(encoding="utf-8"))["outs"][0]
        return f"dvc:{outs['md5']}"
    digest = hashlib.md5()
    for label in sorted(data_dir.rglob("*.txt")):
        digest.update(label.relative_to(data_dir).as_posix().encode())
        digest.update(label.read_bytes())
    return f"nodvc:{digest.hexdigest()[:12]}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="1 epoch on 10%% of train")
    parser.add_argument("--epochs", type=int, help="override config epochs")
    parser.add_argument("--model", help="override base model, e.g. yolov8s.pt")
    parser.add_argument("--merged", action="store_true",
                        help="train on the merged (part, damage_type) dataset, see merge_classes.py")
    parser.add_argument("--name", default="yolov8n-baseline",
                        help="run name; weights exported to models/vision/<name_with_underscores>.pt")
    args = parser.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    tcfg, mcfg = cfg["train"], cfg["mlflow"]
    data_cfg = cfg["merged"] if args.merged else cfg["split"]
    data_dir = Path(data_cfg["output_dir"]).resolve()
    class_mapping = cfg["merged"]["class_mapping"] if args.merged else cfg["class_mapping"]
    data_yaml = data_dir / "data.yaml"
    epochs = 1 if args.smoke else (args.epochs or tcfg["epochs"])
    fraction = 0.1 if args.smoke else 1.0
    run_name = "yolov8n-smoke" if args.smoke else args.name
    base_model = args.model or tcfg["base_model"]


    # We log to MLflow ourselves (required tags); disable Ultralytics' own MLflow callback.
    settings.update({"mlflow": False})
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
    mlflow.set_experiment(mcfg["experiment"])

    tags = {
        "owner": mcfg["owner"],
        "git_commit": git_commit(),
        "data_version": data_version(data_dir),
        "sprint": mcfg["sprint"],
        "smoke": str(args.smoke),
    }
    with mlflow.start_run(run_name=run_name, tags=tags) as run:
        params = {
            "base_model": base_model, "epochs": epochs, "imgsz": tcfg["imgsz"],
            "batch": tcfg["batch"], "patience": tcfg["patience"], "seed": tcfg["seed"],
            "fraction": fraction, "device": "cpu",
            "dataset": f"{cfg['dataset']['workspace']}/{cfg['dataset']['project']}"
                       f"@v{cfg['dataset']['version']}",
            "split_seed": cfg["split"]["seed"],
            "classes": "merged" if args.merged else "original",
        }
        mlflow.log_params(params)

        model = YOLO(base_model)
        model.train(
            data=str(data_yaml), epochs=epochs, imgsz=tcfg["imgsz"], batch=tcfg["batch"],
            workers=tcfg["workers"], patience=tcfg["patience"], seed=tcfg["seed"],
            fraction=fraction, device="cpu", project=str(Path(tcfg["runs_dir"]).resolve()),
            name=run_name, exist_ok=True, plots=True, verbose=False,
        )
        save_dir = Path(model.trainer.save_dir)
        best = save_dir / "weights" / "best.pt"

        # Per-epoch validation curves from Ultralytics' results.csv.
        results_csv = save_dir / "results.csv"
        if results_csv.exists():
            df = pd.read_csv(results_csv)
            df.columns = [c.strip() for c in df.columns]
            for _, row in df.iterrows():
                step = int(row["epoch"])
                for col in ("metrics/mAP50(B)", "metrics/mAP50-95(B)", "train/box_loss"):
                    if col in df.columns:
                        mlflow.log_metric(col.replace("(B)", "").replace("/", "_"),
                                          float(row[col]), step=step)

        # Final evaluation of the best weights on the held-out test split.
        test = YOLO(str(best)).val(data=str(data_yaml), split="test", imgsz=tcfg["imgsz"],
                                   batch=tcfg["batch"], device="cpu", plots=True,
                                   project=str(save_dir), name="test", exist_ok=True)
        metrics = {
            "test_mAP50": float(test.box.map50),
            "test_mAP50_95": float(test.box.map),
            "test_precision": float(test.box.mp),
            "test_recall": float(test.box.mr),
        }
        mlflow.log_metrics(metrics)

        # Artifacts: weights, configs, curves, confusion matrices.
        mlflow.log_artifact(str(best), artifact_path="model")
        mlflow.log_artifact(str(CONFIG_PATH), artifact_path="config")
        mlflow.log_artifact(class_mapping, artifact_path="config")
        for f in [results_csv, *save_dir.glob("*.png"), *(save_dir / "test").glob("*.png")]:
            if f.exists():
                mlflow.log_artifact(str(f), artifact_path="plots")

        if not args.smoke:
            export = Path(tcfg["export_dir"]) / f"{run_name.replace('-', '_')}.pt"
            export.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(best, export)
            mlflow.set_tag("export_path", export.as_posix())

        print("\n=== MLflow ===")
        print("run_id     :", run.info.run_id)
        print("experiment :", mcfg["experiment"])
        print("tags       :", tags)
        for k, v in metrics.items():
            print(f"{k:15s}: {v:.4f}")


if __name__ == "__main__":
    main()