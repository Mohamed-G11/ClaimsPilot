"""The policy config must load whatever the current folder is."""
import subprocess
import sys

from agents.policy import settings


def test_config_is_shared_by_every_policy_module():
    from agents.policy import agent, chunking, index

    assert agent.CONFIG is settings.CONFIG
    assert chunking.CONFIG is settings.CONFIG
    assert index.CONFIG is settings.CONFIG


def test_data_paths_start_at_the_repo_root():
    path = settings.data_path("clauses_file")
    assert path.is_absolute()
    assert path == settings.REPO_ROOT / "data/policy/processed/clauses.jsonl"


def test_import_works_from_another_folder(tmp_path):
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "import agents.policy.agent, agents.policy.chunking, agents.policy.index")
    done = subprocess.run([sys.executable, "-c", code, str(settings.REPO_ROOT)],
                          check=False, cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_policy_llm_model_env_overrides_the_config():
    config = {"llm": {"model": "qwen2.5:7b"}}
    assert settings.apply_env_overrides(config, {"POLICY_LLM_MODEL": "other:1b"})["llm"][
        "model"] == "other:1b"


def test_no_or_empty_env_keeps_the_config():
    for environ in ({}, {"POLICY_LLM_MODEL": "  "}):
        config = {"llm": {"model": "qwen2.5:7b"}}
        assert settings.apply_env_overrides(config, environ)["llm"]["model"] == "qwen2.5:7b"
