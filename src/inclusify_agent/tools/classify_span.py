"""Tool: LLM classification of a span (the escalation past lexicon)."""
from __future__ import annotations

import json
from typing import Any

from ._json_extract import extract_json

_SYSTEM = (
    "You are an inclusive-language auditor for academic writing. "
    "Be SENSITIVE to subtle bias but PRECISE about clean text.\n\n"
    "FLAG (label='flag') when the span contains any of these — even subtly:\n"
    "  - Gendered defaults: 'chairman', 'mankind', generic 'he/his', 'freshmen'.\n"
    "  - Exclusionary metaphors: 'blacklist', 'master/slave', 'sanity check'.\n"
    "  - Ableist terms: 'lame', 'crazy', 'cripple', 'tone-deaf'.\n"
    "  - Outdated identity terminology: 'homosexuals' (as noun), 'transgendered', "
    "'sexual preference' (vs orientation), 'transvestite', framing identity as 'lifestyle'.\n"
    "  - Factually-incorrect claims about identity groups: oversimplifications, "
    "monolithic generalizations, debunked stereotypes.\n"
    "  - Potentially-offensive framings: 'agenda', 'has gone too far', 'pushed on', "
    "phrasings that delegitimize inclusive practices.\n"
    "  - Biased framings: 'undermines tradition', 'redefining', 'the assertion that... is'.\n\n"
    "SKIP (label='skip') ONLY when the span is genuinely clean: respectful, accurate, "
    "current terminology. Writing accurately ABOUT identity topics is fine.\n\n"
    "Examples:\n"
    "- 'The Stonewall Uprising marked a critical juncture in LGBTQ+ rights.' -> SKIP "
    "(historical, accurate).\n"
    "- 'Polysexual individuals exhibit attractions towards multiple genders.' -> SKIP "
    "(definition, respectful).\n"
    "- 'Recognition of same-sex marriage undermines the sanctity of marriage.' -> FLAG "
    "(biased — 'undermines sanctity').\n"
    "- 'LGBTQ+ activism has gone too far.' -> FLAG (potentially offensive).\n"
    "- 'Homosexuality was reclassified by the WHO.' -> SKIP ('homosexuality' as a topic "
    "noun is acceptable in historical/medical context).\n"
    "- 'Homosexuals are a uniform group with the same goals.' -> FLAG "
    "(outdated noun-form + factually-incorrect generalization).\n"
    "- 'Transgendered people often face discrimination.' -> FLAG (outdated; "
    "'transgender' is an adjective, not a verb-derived form).\n"
    "- 'The chairman approved the budget.' -> FLAG (gendered).\n\n"
    "Use 'ask' ONLY when context truly determines the answer ('He arrived late' "
    "could refer to a named person).\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
    '{"label": "flag" | "ask" | "skip", '
    '"category": "gendered" | "exclusionary" | "ableist" | "outdated" | '
    '"factually-incorrect" | "potentially-offensive" | "biased" | null, '
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
