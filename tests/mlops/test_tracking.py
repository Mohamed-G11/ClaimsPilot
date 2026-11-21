"""MLflow helper tests: no MLflow server and no credentials needed."""
from mlops import tracking


def test_required_tags_has_the_four_mandatory_tags(tmp_path):
    tags = tracking.required_tags("mohamed", 3, [tmp_path / "missing.csv"])
    assert set(tags) == {"owner", "git_commit", "data_version", "sprint"}
    assert tags["owner"] == "mohamed"
    assert tags["sprint"] == "3"
    assert all(isinstance(value, str) and value for value in tags.values())


def test_data_version_reads_the_dvc_pointer(tmp_path):
    (tmp_path / "raw.dvc").write_text(
        "outs:\n- md5: abc123.dir\n  size: 10\n  hash: md5\n  path: raw\n", encoding="utf-8")
    assert tracking.data_version(tmp_path / "raw") == "dvc:abc123.dir"


def test_data_version_of_several_paths(tmp_path):
    (tmp_path / "a.csv.dvc").write_text("outs:\n- md5: aaa\n  path: a.csv\n", encoding="utf-8")
    version = tracking.data_version(tmp_path / "a.csv", tmp_path / "b.csv")
    assert version == "dvc:aaa+untracked:b.csv"


def test_data_version_without_data():
    assert tracking.data_version() == "none"


def test_template_credentials_are_not_credentials(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "https://example.test/mlflow")
    monkeypatch.setenv("MLFLOW_TRACKING_USERNAME", "your-dagshub-username")
    monkeypatch.setenv("MLFLOW_TRACKING_PASSWORD", "your-dagshub-token")
    assert tracking.has_credentials() is False


def test_real_looking_credentials_are_accepted(monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "https://example.test/mlflow")
    monkeypatch.setenv("MLFLOW_TRACKING_USERNAME", "someone")
    monkeypatch.setenv("MLFLOW_TRACKING_PASSWORD", "not-a-real-token")
    assert tracking.has_credentials() is True


def test_safe_console_does_not_crash_on_emoji(monkeypatch):
    import io

    raw = io.BytesIO()
    cp1252 = io.TextIOWrapper(raw, encoding="cp1252")     # Windows output redirected to a file
    monkeypatch.setattr(tracking.sys, "stdout", cp1252)
    tracking.safe_console()
    print("\U0001f3c3 View run", file=cp1252)             # what MLflow prints at the end of a run
    cp1252.flush()
    assert raw.getvalue().startswith(rb"\U0001f3c3 View run")    # escaped, not a crash
