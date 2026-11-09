"""Embed the policy clauses and store them in a Chroma vector database.

Usage:  python -m agents.policy.index
Input:  data/policy/processed/clauses.jsonl  (made by agents.policy.chunking)
Output: data/policy/chroma/                   (local vector database, rebuilt anytime)
"""
import json
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG = yaml.safe_load(Path("agents/policy/config.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def embedder():
    """The embedding model, loaded once (downloaded the first time, ~0.5 GB)."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(CONFIG["embedding_model"])


def embed(texts: list[str]) -> list[list[float]]:
    return embedder().encode(texts, normalize_embeddings=True).tolist()


@lru_cache(maxsize=1)
def collection():
    """The Chroma collection holding all clauses of all insurers."""
    import chromadb

    client = chromadb.PersistentClient(path=CONFIG["chroma_dir"])
    return client.get_or_create_collection(CONFIG["collection"],
                                           metadata={"hnsw:space": "cosine"})


def load_clauses() -> list[dict]:
    path = Path(CONFIG["clauses_file"])
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def build() -> None:
    clauses = load_clauses()
    col = collection()
    if col.count():                       # rebuild from scratch
        col.delete(ids=col.get()["ids"])
    # The title is embedded with the text: it carries the meaning of the clause.
    documents = [f"{c['title']}. {c['text']}" for c in clauses]
    col.add(
        ids=[c["clause_id"] for c in clauses],
        documents=documents,
        embeddings=embed(documents),
        metadatas=[{k: c[k] for k in ("insurer", "title", "guarantee", "is_exclusion", "page")}
                   for c in clauses],
    )
    print(f"Indexed {col.count()} clauses in {CONFIG['chroma_dir']}")


if __name__ == "__main__":
    build()
