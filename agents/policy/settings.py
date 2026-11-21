"""Policy agent settings: config.yaml is read once, from this folder.

Every policy module imports CONFIG from here, so the file is parsed a single
time and the agent works whatever the folder it is started from.

    from agents.policy.settings import CONFIG, data_path
    data_path("clauses_file")   # -> <repo>/data/policy/processed/clauses.jsonl

Env vars (optional; when unset, config.yaml is used as it is):
- POLICY_CONFIG     another YAML file instead of config.yaml;
- POLICY_LLM_MODEL  the Ollama model for the answers (overrides llm.model);
- OLLAMA_HOST       the Ollama server (overrides llm.host; read at each call by
                    generation.py, e.g. http://ollama:11434 in docker compose).
"""
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent          # .../agents/policy
REPO_ROOT = HERE.parents[1]                     # the folder holding agents/, data/, api/
CONFIG_PATH = Path(os.getenv("POLICY_CONFIG", HERE / "config.yaml"))


def apply_env_overrides(config: dict, environ=os.environ) -> dict:
    """Replace llm.model by POLICY_LLM_MODEL when it is set and not empty."""
    model = environ.get("POLICY_LLM_MODEL", "").strip()
    if model:
        config["llm"]["model"] = model
    return config


CONFIG: dict = apply_env_overrides(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")))


def data_path(key: str) -> Path:
    """A path from config.yaml; relative paths start at the repository root."""
    path = Path(CONFIG[key])
    return path if path.is_absolute() else REPO_ROOT / path
