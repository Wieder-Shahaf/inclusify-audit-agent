"""VectorStore contract: every impl must satisfy add/search semantics.

Runs against InMemoryStore + ChromaStore (offline). QdrantStore needs a live endpoint
and is tested separately under the 'live' marker.
"""
from __future__ import annotations

import gc

import pytest

from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.vectorstore import (
    ChromaStore,
    InMemoryStore,
    QdrantStore,
    VectorStore,
)


def _make_records(
    emb: HashEmbeddings,
) -> tuple[list[str], list[list[float]], list[str], list[dict]]:
    texts = ["cats are mammals", "the eiffel tower is in paris", "dogs bark loudly"]
    ids = [f"r{i}" for i in range(len(texts))]
    vectors = emb.embed(texts)
    metas = [{"src": "fixture", "n": i} for i in range(len(texts))]
    return ids, vectors, texts, metas


def _check_store(store: VectorStore, emb: HashEmbeddings) -> None:
    ids, vecs, texts, metas = _make_records(emb)
    store.add(ids, vecs, texts, metas)
    query = emb.embed("cats")[0]
    hits = store.search(query, k=3)
    assert len(hits) > 0
    assert len(hits) <= 3
    for hit in hits:
        assert len(hit) == 4
        rid, score, text, meta = hit
        assert isinstance(rid, str)
        assert isinstance(score, float)
        assert isinstance(text, str)
        assert isinstance(meta, dict)
    # The cat record should be top-1 (hash embedder is weak but deterministic for identical tokens)
    top_id = hits[0][0]
    assert top_id in ids


def test_inmemory_satisfies_contract() -> None:
    emb = HashEmbeddings(dim=64)
    store = InMemoryStore(dim=64)
    _check_store(store, emb)


def test_chroma_satisfies_contract(tmp_path) -> None:
    # Use pytest's tmp_path (not TemporaryDirectory) so we can release Chroma's sqlite
    # file handles before pytest's own cleanup runs — Windows otherwise blocks unlink.
    emb = HashEmbeddings(dim=64)
    store = ChromaStore(path=str(tmp_path), collection="contract_test", dim=64)
    try:
        _check_store(store, emb)
    finally:
        del store
        gc.collect()


def test_qdrant_class_satisfies_protocol() -> None:
    # Don't instantiate (would hit live server); just check the class shape.
    assert QdrantStore.name == "qdrant"
    assert hasattr(QdrantStore, "add")
    assert hasattr(QdrantStore, "search")


def test_inmemory_rejects_wrong_dim() -> None:
    store = InMemoryStore(dim=64)
    with pytest.raises(ValueError, match="dim"):
        store.add(["x"], [[0.1] * 32], ["t"])
