"""Tool: LLM classification of a span (the escalation past lexicon)."""
from __future__ import annotations

import json
from typing import Any


def classify_span(llm: Any, *, span: str, context: str = "") -> dict[str, Any]:
    """Ask the LLM to flag/skip a span. Returns a parsed JSON dict.

    Contract (BUILD_PLAN §3): the LLM (MockLLM or live) returns JSON with at minimum
    {"label": "flag"|"skip", "category": str|None, "reason": str}.
    """
    prompt = (
        "Classify this span for non-inclusive language.\n"
        f"span: {span!r}\ncontext: {context!r}"
    )
    raw = llm.complete(prompt=prompt, task="classify", span=span, context=context)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return {"label": "skip", "category": None, "reason": "unparseable LLM output", "raw": raw}
    # Schema floor
    result.setdefault("label", "skip")
    result.setdefault("category", None)
    result.setdefault("reason", "")
    return result
