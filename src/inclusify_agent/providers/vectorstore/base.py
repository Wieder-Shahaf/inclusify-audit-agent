"""VectorStore interface. Phase 2 wires chroma + inmemory + qdrant."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Minimal vector store contract: add and search.

    Records carry an id, vector, text, and arbitrary metadata. Search returns the top-K
    matches as (id, score, text, metadata) tuples — score semantics depend on the impl
    (cosine for Chroma/Qdrant by default).
    """

    name: str
    dim: int

    def add(
        self,
        ids: list[str],
        vectors: list[list[float]],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        """Upsert records. ids/vectors/texts must be the same length."""
        ...

    def search(
        self, query_vector: list[float], k: int = 5
    ) -> list[tuple[str, float, str, dict]]:
        """Return top-K matches: (id, score, text, metadata)."""
        ...
