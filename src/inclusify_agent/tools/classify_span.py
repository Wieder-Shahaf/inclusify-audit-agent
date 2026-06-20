"""Tool: LLM classification of a span (the escalation past lexicon)."""
from __future__ import annotations

import json
from typing import Any

from ._json_extract import extract_json

_SYSTEM = (
    "You are an inclusive-language auditor for academic writing. "
    "Given a span and its surrounding context, decide whether the span contains "
    "non-inclusive language (gendered terms, exclusionary metaphors, ableist "
    "phrasing, or culturally-insensitive references).\n\n"
    "Choose the label carefully:\n"
    '- "flag": clear non-inclusive language; you are confident.\n'
    '- "ask":  ambiguous or context-dependent (a term that is sometimes biased, '
    "sometimes neutral, e.g., a generic 'he' that might refer to a specific person). "
    "Use this when a clarifying question would help.\n"
    '- "skip": clean text; no issue.\n\n'
    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
    '{"label": "flag" | "ask" | "skip", '
    '"category": "gendered" | "exclusionary" | "ableist" | "culturally-insensitive" | null, '
    '"reason": "short explanation"}'
)


def classify_span(llm: Any, *, span: str, context: str = "") -> dict[str, Any]:
    """Ask the LLM to flag/skip a span. Returns a parsed JSON dict.

    Contract (BUILD_PLAN §3): the LLM (MockLLM or live) returns JSON with at minimum
    {"label": "flag"|"skip", "category": str|None, "reason": str}.
    """
    prompt = (
        f"span: {span!r}\n"
        f"context_before: {context!r}\n\n"
        "Return the classification JSON now."
    )
    raw = llm.complete(prompt=prompt, system=_SYSTEM, task="classify", span=span, context=context)
    try:
        result = extract_json(raw)
        if not isinstance(result, dict):
            raise json.JSONDecodeError("not a dict", raw, 0)
    except json.JSONDecodeError:
        return {"label": "skip", "category": None, "reason": "unparseable LLM output", "raw": raw}
    # Schema floor
    result.setdefault("label", "skip")
    result.setdefault("category", None)
    result.setdefault("reason", "")
    # Normalize label to known set.
    if result["label"] not in ("flag", "ask", "skip"):
        label_str = str(result.get("label", "")).lower()
        if label_str.startswith("flag"):
            result["label"] = "flag"
        elif label_str.startswith("ask"):
            result["label"] = "ask"
        else:
            result["label"] = "skip"
    return result
