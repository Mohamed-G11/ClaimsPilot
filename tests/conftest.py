"""Tests never send anything to Langfuse and never warm up the LLM.

Some code loads .env into the environment (mlops/tracking.py), which would turn
tracing on with the real keys. Before every test, the Langfuse keys are removed,
the kill switch is set and the cached client is dropped. Tracing tests use a fake
client (tests/test_tracing.py).
"""
import pytest

from api import tracing


@pytest.fixture(autouse=True)
def no_langfuse(monkeypatch):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL",
                 "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAIMSPILOT_TRACING", "0")
    monkeypatch.setenv("CLAIMSPILOT_WARMUP", "0")      # no LLM warm-up call in tests
    tracing.client.cache_clear()
    yield
    if hasattr(tracing.client, "cache_clear"):     # a test may have replaced client()
        tracing.client.cache_clear()
