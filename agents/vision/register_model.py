"""Register a trained vision model in the MLflow Model Registry (DagsHub).

The weights logged by train.py under the run's `model/` artifact folder become a new
version of the registered model `claimspilot-vision-yolo`.

Usage (from the repo root; credentials from .env):
    python -m agents.vision.register_model <run_id> [--name claimspilot-vision-yolo]
"""
import argparse
import os

from dotenv import load_dotenv
from mlflow.exceptions import MlflowException
from mlflow.tracking import MlflowClient

load_dotenv()  # MLFLOW_TRACKING_URI + DagsHub credentials from .env (AGENTS.md section 6)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--name", default="claimspilot-vision-yolo")
    args = parser.parse_args()

    client = MlflowClient(os.getenv("MLFLOW_TRACKING_URI"))
    run = client.get_run(args.run_id)

    try:
        client.create_registered_model(
            args.name, description="ClaimsPilot vision agent: YOLOv8 car damage detector")
    except MlflowException as err:  # already registered -> just add a new version
        if "RESOURCE_ALREADY_EXISTS" not in str(err) and "already exists" not in str(err):
            raise

    version = client.create_model_version(
        name=args.name,
        source=f"{run.info.artifact_uri}/model",
        run_id=args.run_id,
        tags={k: run.data.tags[k] for k in ("owner", "git_commit", "data_version", "sprint")
              if k in run.data.tags},
        description=f"{run.info.run_name}: test mAP50 = "
                    f"{run.data.metrics.get('test_mAP50', float('nan')):.3f}",
    )
    print(f"Registered '{args.name}' version {version.version} from run {args.run_id} "
          f"({run.info.run_name}, test_mAP50={run.data.metrics.get('test_mAP50')})")


if __name__ == "__main__":
    main()