
import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

import mlflow
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from agents.nlp.agent import run
from claimspilot.schemas import ClaimInput, Damage, VisionResult


LABELS = ["consistent", "inconsistent", "uncertain"]
ROOT = Path(__file__).resolve().parents[2]


def parse_parts(value):
    """Parse vehicle parts separated by pipes or semicolons."""
    if not value:
        return []

    return [
        part.strip()
        for part in re.split(r"[|;]", value)
        if part.strip()
    ]


def get_git_commit():
    """Return the current Git commit hash."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_dataset_version(dataset):
    """Return a SHA-256 hash of the dataset contents."""
    return hashlib.sha256(
        Path(dataset).read_bytes()
    ).hexdigest()


def evaluate(dataset):
    dataset = Path(dataset)

    # Load dataset
    with dataset.open(
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)

        required = {
            "claim_id",
            "language",
            "text",
            "photo_parts",
            "label",
        }

        if not reader.fieldnames:
            raise ValueError("Dataset is empty or missing a header")

        if not required.issubset(reader.fieldnames):
            missing = required - set(reader.fieldnames)
            raise ValueError(
                f"Dataset is missing required columns: {sorted(missing)}"
            )

        rows = list(reader)

    if not rows:
        raise ValueError("Dataset is empty")

    y_true = []
    y_pred = []

    true_part_sets = []
    pred_part_sets = []

    predictions = []

    # Evaluate every claim
    for row in rows:
        claim = ClaimInput(
            claim_id=row["claim_id"],
            photo_paths=[],
            text=row["text"],
            policy_id="evaluation",
            language=row["language"],
        )

        photo_parts = parse_parts(row["photo_parts"])

        vision = VisionResult(
            claim_id=row["claim_id"],
            damages=[
                Damage(
                    part=part,
                    damage_type="unknown",
                    bbox=[0, 0, 1, 1],
                    confidence=1.0,
                )
                for part in photo_parts
            ],
            severity="minor",
            model_version="evaluation-ground-truth",
        )

        result = run(claim, vision)

        y_true.append(row["label"])
        y_pred.append(result.consistency)

        # Ground-truth text extraction labels
        if "true_parts" in row:
            expected_parts = parse_parts(row["true_parts"])
        elif "described_parts" in row:
            expected_parts = parse_parts(row["described_parts"])
        else:
            expected_parts = None

        if expected_parts is not None:
            true_part_sets.append(set(expected_parts))
            pred_part_sets.append(set(result.described_parts))

        predictions.append({
            "claim_id": row["claim_id"],
            "true_label": row["label"],
            "predicted_label": result.consistency,
            "predicted_parts": result.described_parts,
            "score": float(result.score),
        })

    # Classification metrics
    macro_f1 = f1_score(
        y_true,
        y_pred,
        labels=LABELS,
        average="macro",
        zero_division=0,
    )

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=LABELS,
        zero_division=0,
    )

    metrics = {
        "macro_f1": float(macro_f1),
    }

    for i, label in enumerate(LABELS):
        metrics[f"{label}_precision"] = float(precision[i])
        metrics[f"{label}_recall"] = float(recall[i])
        metrics[f"{label}_f1"] = float(f1[i])

    # Vehicle-part extraction metrics
    if true_part_sets:
        tp = sum(
            len(true & pred)
            for true, pred in zip(
                true_part_sets,
                pred_part_sets,
            )
        )

        fp = sum(
            len(pred - true)
            for true, pred in zip(
                true_part_sets,
                pred_part_sets,
            )
        )

        fn = sum(
            len(true - pred)
            for true, pred in zip(
                true_part_sets,
                pred_part_sets,
            )
        )

        part_precision = (
            tp / (tp + fp)
            if tp + fp
            else 0.0
        )

        part_recall = (
            tp / (tp + fn)
            if tp + fn
            else 0.0
        )

        part_f1 = (
            2 * part_precision * part_recall
            / (part_precision + part_recall)
            if part_precision + part_recall
            else 0.0
        )

        metrics.update({
            "part_micro_precision": float(part_precision),
            "part_micro_recall": float(part_recall),
            "part_micro_f1": float(part_f1),
        })

    # Confusion matrix
    matrix = confusion_matrix(
        y_true,
        y_pred,
        labels=LABELS,
    )

    print("\nClassification report:")
    print(
        classification_report(
            y_true,
            y_pred,
            labels=LABELS,
            zero_division=0,
        )
    )

    print("Macro F1:", round(macro_f1, 4))

    # Reproducibility metadata
    git_commit = get_git_commit()
    dataset_version = get_dataset_version(dataset)

    # Save evaluation artifacts and log to MLflow
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp)

        (output / "confusion_matrix.json").write_text(
            json.dumps(
                {
                    "labels": LABELS,
                    "matrix": matrix.tolist(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        (output / "predictions.json").write_text(
            json.dumps(
                predictions,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        mlflow.set_experiment("claimspilot-nlp")

        with mlflow.start_run(
            run_name="sprint2-dev-baseline"
        ):
            mlflow.log_param(
                "dataset",
                dataset.name,
            )

            mlflow.log_param(
                "dataset_size",
                len(rows),
            )

            mlflow.set_tags({
                "owner": "hend",
                "sprint": "2",
                "evaluation_split": "development",
                "git_commit": git_commit,
                "dataset_version": dataset_version,
            })

            mlflow.log_metrics(metrics)

            mlflow.log_artifacts(
                str(output)
            )

    print("\nMLflow logging complete.")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate ClaimsPilot NLP agent"
    )

    parser.add_argument(
        "--dataset",
        default=str(
            ROOT / "data/nlp/synthetic_claims_v3.csv"
        ),
        help="Path to the evaluation CSV dataset",
    )

    args = parser.parse_args()

    evaluate(args.dataset)

