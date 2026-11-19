"""Policy agent settings: config.yaml is read once, from this folder.

Every policy module imports CONFIG from here, so the file is parsed a single
time and the agent works whatever the folder it is started from.

    from agents.policy.settings import CONFIG, data_path
    data_path("clauses_file")   # -> <repo>/data/policy/processed/clauses.jsonl

POLICY_CONFIG (env var) can point to another YAML file, e.g. in Docker.
"""
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent          # .../agents/policy
REPO_ROOT = HERE.parents[1]                     # the folder holding agents/, data/, api/
CONFIG_PATH = Path(os.getenv("POLICY_CONFIG", HERE / "config.yaml"))

CONFIG: dict = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def data_path(key: str) -> Path:
    """A path from config.yaml; relative paths start at the repository root."""
    path = Path(CONFIG[key])
    return path if path.is_absolute() else REPO_ROOT / path
