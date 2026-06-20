"""Chroma persistent store. Local file-based; no service, no key."""
from __future__ import annotations

from typing import Any


class ChromaStore:
    name = "chroma"

    def __init__(
        self,
        path: str = ".chroma",
        collection: str = "inclusify_eric",
        dim: int = 64,
    ) -> None:
        try:
            import chromadb
        except ImportError as e:
            raise RuntimeError("chromadb not installed") from e
        self._client = chromadb.PersistentClient(path=path)
        # Always pass embedding_function=None — we embed externally; Chroma must not embed.
        self._collection = self._client.get_or_create_collection(
            name=collection, embedding_function=None
        )
        self.dim = dim

    def add(
        self,
        ids: list[str],
        vectors: list[list[float]],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not (len(ids) == len(vectors) == len(texts)):
            raise ValueError("ids, vectors, texts must be same length")
        metas = metadatas or [{} for _ in ids]
        # Chroma rejects empty metadata dicts in some versions — sentinel-fill.
        metas = [m or {"_": "_"} for m in metas]
        self._collection.upsert(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)

    def search(
        self, query_vector: list[float], k: int = 5
    ) -> list[tuple[str, float, str, dict]]:
        res: Any = self._collection.query(query_embeddings=[query_vector], n_results=k)
        out: list[tuple[str, float, str, dict]] = []
        ids = res.get("ids", [[]])[0]
        dists = res.get("distances", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        for rid, dist, doc, meta in zip(ids, dists, docs, metas, strict=True):
            # Chroma returns distance (lower=better); convert to similarity for caller.
            score = 1.0 - float(dist)
            out.append((rid, score, doc, meta or {}))
        return out
