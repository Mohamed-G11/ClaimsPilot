"""Copy an MLflow run from one tracking server to another (e.g. local -> DagsHub).

Used once to move the sprint-1 baseline, trained against a local MLflow server,
to the shared DagsHub server without retraining. Params, tags, full metric
history and artifacts are copied; tags can be overridden (e.g. data_version).

Usage (from the repo root; credentials for the target come from .env):
    python -m agents.vision.migrate_run <run_id> --source http://localhost:5000 \
        --tag data_version=dvc:<md5>
"""
import argparse
import os
import tempfile

from mlflow.entities import Metric, Param
from mlflow.tracking import MlflowClient

try:  # optional: load MLFLOW_TRACKING_* from .env like mlops/test_mlflow_connection.py
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--source", default="http://localhost:5000")
    parser.add_argument("--target", default=os.getenv("MLFLOW_TRACKING_URI"))
    parser.add_argument("--tag", action="append", default=[], help="key=value override")
    args = parser.parse_args()
    if not args.target:
        raise SystemExit("No target: set MLFLOW_TRACKING_URI (.env) or pass --target.")

    src, dst = MlflowClient(args.source), MlflowClient(args.target)
    run = src.get_run(args.run_id)
    exp_name = src.get_experiment(run.info.experiment_id).name
    exp = dst.get_experiment_by_name(exp_name)
    exp_id = exp.experiment_id if exp else dst.create_experiment(exp_name)

    tags = {k: v for k, v in run.data.tags.items() if not k.startswith("mlflow.")}
    tags.update(dict(t.split("=", 1) for t in args.tag))
    tags["migrated_from"] = f"{args.source}/runs/{args.run_id}"

    new = dst.create_run(exp_id, start_time=run.info.start_time, tags=tags,
                         run_name=run.info.run_name)
    new_id = new.info.run_id

    metrics = [
        Metric(m.key, m.value, m.timestamp, m.step)
        for key in run.data.metrics
        for m in src.get_metric_history(args.run_id, key)
    ]
    params = [Param(k, v) for k, v in run.data.params.items()]
    for i in range(0, max(len(metrics), 1), 500):  # MLflow batch limit: 1000 metrics
        dst.log_batch(new_id, metrics=metrics[i : i + 500],
                      params=params if i == 0 else [])

    with tempfile.TemporaryDirectory() as tmp:
        local = src.download_artifacts(args.run_id, "", tmp)
        dst.log_artifacts(new_id, local)

    dst.set_terminated(new_id, status=run.info.status, end_time=run.info.end_time)
    print(f"Copied run {args.run_id} -> {new_id} in experiment '{exp_name}' on {args.target}")
    print(f"{len(params)} params, {len(metrics)} metric points, tags: {tags}")


if __name__ == "__main__":
    main()