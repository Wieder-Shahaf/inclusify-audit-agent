"""In-memory vector store. Brute-force cosine search; for tests + small fixtures."""
from __future__ import annotations

import math


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class InMemoryStore:
    name = "inmemory"

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._records: dict[str, tuple[list[float], str, dict]] = {}

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
        if len(metas) != len(ids):
            raise ValueError("metadatas length mismatch")
        for i, vec, text, meta in zip(ids, vectors, texts, metas, strict=True):
            if len(vec) != self.dim:
                raise ValueError(f"vector dim {len(vec)} != store dim {self.dim}")
            self._records[i] = (vec, text, meta)

    def search(
        self, query_vector: list[float], k: int = 5
    ) -> list[tuple[str, float, str, dict]]:
        if len(query_vector) != self.dim:
            raise ValueError(f"query dim {len(query_vector)} != store dim {self.dim}")
        scored = [
            (rid, _cosine(query_vector, vec), text, meta)
            for rid, (vec, text, meta) in self._records.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]
