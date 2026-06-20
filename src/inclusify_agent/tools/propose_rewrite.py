"""Tool: LLM-generated inclusive rewrite of a flagged span."""
from __future__ import annotations

import json
from typing import Any


def propose_rewrite(llm: Any, *, span: str, category: str | None = None) -> dict[str, Any]:
    """Return {"rewrite": str, "preserves_meaning": bool}."""
    raw = llm.complete(
        prompt=f"Propose an inclusive rewrite.\nspan: {span!r}\ncategory: {category}",
        task="rewrite",
        span=span,
        category=category or "",
    )
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return {"rewrite": span, "preserves_meaning": False, "error": "unparseable LLM output"}
    out.setdefault("rewrite", span)
    out.setdefault("preserves_meaning", True)
    return out
