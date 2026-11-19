"""Shared MLflow helper: the four tags every ClaimsPilot run must carry.

AGENTS.md section 6 asks for `owner`, `git_commit`, `data_version` and `sprint`
on every training / evaluation run. Use this helper instead of rewriting them:

    from mlops.tracking import start_run

    with start_run("claimspilot-policy", run_name="eval", owner="mohamed",
                   sprint=3, data=["data/policy/eval_claims.csv"]):
        mlflow.log_metric("coverage_accuracy", 0.9)

`mlflow` is imported lazily, so `required_tags()` works without it.
"""
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = {"", "your-dagshub-username", "your-dagshub-token"}


def git_commit() -> str:
    """Current commit hash, with "-dirty" when tracked files have uncommitted changes."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                                      text=True).strip()
        changes = subprocess.check_output(["git", "status", "--porcelain",
                                           "--untracked-files=no"], cwd=REPO_ROOT, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if changes.strip() else sha


def data_version(*paths: str | Path) -> str:
    """DVC md5 of each data path, read from its `.dvc` pointer file.

    data_version("data/policy/raw") -> "dvc:3f2a..."      (reads data/policy/raw.dvc)
    Several paths are joined with "+". A path without pointer gives "untracked:<name>".
    """
    versions = []
    for path in paths:
        path = Path(path)
        path = path if path.is_absolute() else REPO_ROOT / path
        pointer = path.with_name(path.name + ".dvc")
        if pointer.exists():
            out = yaml.safe_load(pointer.read_text(encoding="utf-8"))["outs"][0]
            versions.append(f"dvc:{out['md5']}")
        else:
            versions.append(f"untracked:{path.name}")
    return "+".join(versions) if versions else "none"


def required_tags(owner: str, sprint: int | str, data: list[str | Path] | None = None) -> dict:
    """The four mandatory tags, as strings."""
    return {
        "owner": owner,
        "git_commit": git_commit(),
        "data_version": data_version(*(data or [])),
        "sprint": str(sprint),
    }


def has_credentials() -> bool:
    """True when .env gives a tracking URI and real (non-template) credentials."""
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    values = [os.getenv(name, "") for name in
              ("MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_USERNAME", "MLFLOW_TRACKING_PASSWORD")]
    return all(value not in PLACEHOLDERS for value in values)


def safe_console() -> None:
    """MLflow prints emoji ("🏃 View run ...") when a run ends. On Windows, output
    redirected to a file uses cp1252, which cannot encode them: the print crashed
    the end of the run. Unencodable characters are now escaped instead."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


@contextmanager
def start_run(experiment: str, run_name: str, owner: str, sprint: int | str,
              data: list[str | Path] | None = None):
    """Open an MLflow run in `experiment` with the required tags already set."""
    import mlflow
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
    safe_console()
    mlflow.set_experiment(experiment)
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.set_tags(required_tags(owner, sprint, data))
        yield run
