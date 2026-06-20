"""Qdrant vector store (live, on the work VM).

Collection lifecycle: created on first add() with the configured dim and cosine distance.
Teardown is OUT OF SCOPE here — use scripts/teardown_vm.sh (requires interactive TTY).
"""
from __future__ import annotations

import uuid
from typing import Any


class QdrantStore:
    name = "qdrant"

    def __init__(
        self,
        url: str,
        collection: str,
        dim: int,
        api_key: str = "",
    ) -> None:
        if not url or not collection:
            raise ValueError("QdrantStore requires url and collection")
        try:
            from qdrant_client import QdrantClient
        except ImportError as e:
            raise RuntimeError(
                "qdrant-client not installed. Install with: pip install '.[live]'"
            ) from e
        self._client = QdrantClient(url=url, api_key=api_key or None)
        self._collection = collection
        self.dim = dim
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        from qdrant_client.http.models import Distance, VectorParams

        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )

    def add(
        self,
        ids: list[str],
        vectors: list[list[float]],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        from qdrant_client.http.models import PointStruct

        if not (len(ids) == len(vectors) == len(texts)):
            raise ValueError("ids, vectors, texts must be same length")
        metas = metadatas or [{} for _ in ids]
        points = []
        for rid, vec, text, meta in zip(ids, vectors, texts, metas, strict=True):
            # Qdrant requires int or UUID point IDs — derive a UUID from any string id.
            try:
                point_id: Any = int(rid)
            except (TypeError, ValueError):
                point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(rid)))
            payload = {"_orig_id": str(rid), "text": text, **(meta or {})}
            points.append(PointStruct(id=point_id, vector=vec, payload=payload))
        self._client.upsert(collection_name=self._collection, points=points)

    def search(
        self, query_vector: list[float], k: int = 5
    ) -> list[tuple[str, float, str, dict]]:
        hits = self._client.search(
            collection_name=self._collection, query_vector=query_vector, limit=k, with_payload=True
        )
        out: list[tuple[str, float, str, dict]] = []
        for h in hits:
            payload = h.payload or {}
            rid = str(payload.pop("_orig_id", h.id))
            text = str(payload.pop("text", ""))
            out.append((rid, float(h.score), text, payload))
        return out
