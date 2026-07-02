"""Tool: vector-store retrieval for grounding a finding.

Retrieval shape mirrors the Medium-Article-RAG assignment: over-fetch x5, then
keep the highest-scoring chunk per source document (dedup by doc_id), then
truncate to k. Adjacent chunks of one paper are near-duplicates in embedding
space; without dedup, k citations can all be slices of the same document.
"""
from __future__ import annotations

from typing import Any

from .schemas import Citation

_OVER_FETCH = 5


def _dedup_by_doc(hits: list[tuple], k: int) -> list[tuple]:
    """Keep the best-scoring hit per doc_id, preserving score order.

    Hits without a doc_id (e.g. offline seed docs) dedup by their own id.
    """
    seen: set[str] = set()
    out: list[tuple] = []
    for hit in hits:
        rid, _score, _text, meta = hit
        key = (meta or {}).get("doc_id") or rid
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
        if len(out) >= k:
            break
    return out


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
    hits = store.search(vec, k=k * _OVER_FETCH)
    return [
        Citation(id=rid, text=text, score=float(score), metadata=meta)
        for rid, score, text, meta in _dedup_by_doc(hits, k)
    ]
