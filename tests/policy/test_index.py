"""Index tests with a fake collection: no chromadb, no embedding model."""
import pytest

from agents.policy import index


class FakeCollection:
    def __init__(self, size):
        self.size = size

    def count(self):
        return self.size


def test_empty_index_gives_a_clear_error(monkeypatch):
    monkeypatch.setattr(index, "collection", lambda: FakeCollection(0))
    with pytest.raises(index.EmptyIndexError, match="python -m agents.policy.index"):
        index.ready_collection()


def test_filled_index_is_returned(monkeypatch):
    fake = FakeCollection(185)
    monkeypatch.setattr(index, "collection", lambda: fake)
    assert index.ready_collection() is fake
