"""Tool: vector-store retrieval for grounding a finding."""
from __future__ import annotations

from typing import Any

from .schemas import Citation


def retrieve_citation(
    store: Any,
    embedder: Any,
    *,
    query: str,
    k: int = 3,
) -> list[Citation]:
    """Embed the query, search the store, return Citation objects (may be empty)."""
    if not query.strip():
        return []
    vec = embedder.embed(query)[0]
    hits = store.search(vec, k=k)
    return [
        Citation(id=rid, text=text, score=float(score), metadata=meta)
        for rid, score, text, meta in hits
    ]
