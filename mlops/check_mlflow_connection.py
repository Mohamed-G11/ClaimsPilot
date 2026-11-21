"""Check that your .env lets you log to the shared MLflow server (DagsHub).

Usage:  python -m mlops.check_mlflow_connection
Logs one tiny run to the experiment "claimspilot-platform-test".
"""
import sys

from mlops.tracking import has_credentials, start_run


def main() -> int:
    if not has_credentials():
        print("MLflow credentials missing: copy .env.example to .env and fill in your "
              "DagsHub username and token.")
        return 1

    import mlflow

    with start_run("claimspilot-platform-test", run_name="connection-test",
                   owner="mohamed", sprint=3):
        mlflow.log_metric("connection_ok", 1)
    print("Run logged. Check the Experiments tab on DagsHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
