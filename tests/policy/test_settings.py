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
