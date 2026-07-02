"""Why-RAG chain: on-demand grounded explanation for a flagged span.

The PRD's interactive "Why?" stage, shaped like the Medium-Article-RAG assignment:
retrieve (over-fetch + dedup via retrieve_citation) -> numbered-context augmented
prompt with a strict refusal rule -> one LLM call. The call uses task="ground", so
it records as the GroundingChecker module in the steps trace.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .eric_live_search import eric_live_enabled, eric_live_search
from .retrieve_citation import retrieve_citation
from .schemas import Citation

WHY_TOP_K = 5

REFUSAL = "I don't know based on the provided corpus data."

_WHY_SYSTEM = (
    "You are the grounding module of an inclusivity audit agent for higher "
    "education. Explain WHY a flagged phrase is considered non-inclusive, strictly "
    "and only based on the retrieved corpus passages provided to you. Do not use "
    "external knowledge. Quote or paraphrase the passages, citing them inline as "
    f'[1], [2], etc. If the passages do not support an explanation, respond: "{REFUSAL}" '
    "Be concise: 2-4 sentences."
)


def build_why_prompt(question: str, citations: list[Citation]) -> str:
    """Numbered context blocks + the question — the augmented prompt."""
    if not citations:
        return f"Context: (no passages retrieved)\n\nQuestion: {question}"
    blocks: list[str] = []
    for i, c in enumerate(citations, start=1):
        meta = c.metadata or {}
        header = f"[{i}] {meta.get('title') or c.id}"
        if meta.get("year"):
            header += f" ({meta['year']})"
        if meta.get("url"):
            header += f"\n    {meta['url']}"
        blocks.append(f"{header}\n{c.text}")
    context = "\n\n---\n\n".join(blocks)
    return f"Context (retrieved corpus passages):\n\n{context}\n\nQuestion: {question}"


def explain_why(
    llm: Any,
    store: Any,
    embedder: Any,
    *,
    span: str,
    category: str | None = None,
    reason: str | None = None,
    k: int = WHY_TOP_K,
) -> dict[str, Any]:
    """Retrieve -> augment -> generate. Returns explanation + citations + prompt."""
    question = f"Why is the phrase '{span}' considered non-inclusive"
    if category:
        question += f" (category: {category})"
    question += "?"
    if reason:
        question += f" The auditor's initial reason was: {reason}"

    query = f"{category or 'inclusive language'}: {span}"
    citations = retrieve_citation(store, embedder, query=query, k=k)
    # Weak local grounding -> pull fresh ERIC abstracts too (env-gated, never raises).
    if eric_live_enabled() and (not citations or citations[0].score < 0.35):
        live = eric_live_search(embedder, query=query, k=3)
        citations = sorted(citations + live, key=lambda c: c.score, reverse=True)[:k]
    prompt = build_why_prompt(question, citations)
    raw = llm.complete(
        prompt, system=_WHY_SYSTEM, task="ground",
        citation=citations[0].text if citations else "",
    )
    return {
        "explanation": (raw or "").strip() or REFUSAL,
        "citations": [asdict(c) for c in citations],
        "augmented_prompt": prompt,
    }
