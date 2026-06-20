"""Tool: LLM-generated inclusive rewrite of a flagged span."""
from __future__ import annotations

import json
from typing import Any

from ._json_extract import extract_json
from .schemas import LexiconHit

_SYSTEM = (
    "You rewrite text to use inclusive language while preserving the original meaning. "
    "Replace gendered/exclusionary/ableist terms with inclusive alternatives. "
    "If a list of known-flagged terms with suggested replacements is provided, USE THOSE "
    "replacements; do not invent alternatives for them.\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
    '{"rewrite": "the rewritten span", "preserves_meaning": true | false}'
)


def _format_hints(hits: list[LexiconHit] | None) -> str:
    if not hits:
        return ""
    lines = ["", "Known-flagged terms in this span (replace these specifically):"]
    seen: set[str] = set()
    for h in hits:
        if h.term in seen:
            continue
        seen.add(h.term)
        alts = ", ".join(h.alternatives) if h.alternatives else "(any inclusive alternative)"
        lines.append(f"  - {h.term!r} ({h.category}) -> {alts}")
    return "\n".join(lines)


def propose_rewrite(
    llm: Any,
    *,
    span: str,
    category: str | None = None,
    lexicon_hits: list[LexiconHit] | None = None,
) -> dict[str, Any]:
    """Return {"rewrite": str, "preserves_meaning": bool}.

    `lexicon_hits` is optional but recommended when known: the system prompt tells the
    LLM to prefer the lexicon's suggested replacements over inventing its own. This
    closes the "Gemma missed blacklist" gap from the first live run.
    """
    hint_block = _format_hints(lexicon_hits)
    prompt = (
        f"span: {span!r}\n"
        f"category: {category}"
        f"{hint_block}\n\n"
        "Return the rewrite JSON now."
    )
    raw = llm.complete(
        prompt=prompt, system=_SYSTEM, task="rewrite",
        span=span, category=category or "",
    )
    try:
        out = extract_json(raw)
        if not isinstance(out, dict):
            raise json.JSONDecodeError("not a dict", raw, 0)
    except json.JSONDecodeError:
        return {"rewrite": span, "preserves_meaning": False, "error": "unparseable LLM output"}
    out.setdefault("rewrite", span)
    out.setdefault("preserves_meaning", True)
    return out
