"""Tool: the v2 ReportConsolidator LLM call (PRD §4 [4], BUILD_PLAN R6).

One call, only when at least one investigation confirmed: decide which confirmed
findings to retract (contradicts the doctrine, or duplicates another finding kept),
group recurring findings into document-level patterns, and order the kept ids by
severity. Skipped entirely -- no LLM call -- when nothing confirmed (PRD §8's
skip-if-empty lever).
"""
from __future__ import annotations

import json
from typing import Any

from ._json_extract import extract_json
from .schemas import Investigation

_SKIPPED_RESULT = {
    "kept": [], "retracted": [], "patterns": [],
    "summary": "No inclusivity issues were confirmed.", "skipped": True,
}

# The exact return contract -- stated once here, then repeated verbatim in the user
# prompt as a reminder (same KV-cache-friendly pattern as audit_window/investigate).
_CONTRACT = (
    '{"kept": ["id", ...], '
    '"retracted": [{"id": "...", "rationale": "..."}], '
    '"patterns": [{"framing": "...", "category": "...", "finding_ids": ["..."]}], '
    '"summary": "1-2 sentences"}'
)

# ONE constant (KV-cache): all variable content (the findings themselves) lives in
# the user prompt built by `_user_prompt`, never here.
_SYSTEM = (
    "You are the report consolidator of an inclusivity audit of English academic "
    "text. You receive every CONFIRMED finding from the evidence-investigation "
    "stage, compactly described. Decide:\n"
    "1. Retract any finding that contradicts the audit's doctrine (its span's "
    "subject is actually the correction or affirmation, not a harmful view) or "
    "duplicates another finding you are keeping -- give each retraction a "
    "one-sentence rationale.\n"
    "2. Group recurring or related findings into document-level patterns (a shared "
    "framing repeated across findings, e.g. the same gendered default used several "
    "times).\n"
    "3. Order the kept ids by severity, most severe first: factually-incorrect and "
    "biased findings are most severe; gendered lexicon-fix findings are least "
    "severe.\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, in exactly this "
    "shape:\n" + _CONTRACT
)


def _evidence_titles(evidence: list[dict[str, Any]]) -> list[str]:
    return [str(e["title"]) for e in (evidence or [])[:2] if e.get("title")]


def _compact(inv: Investigation) -> dict[str, Any]:
    """One confirmed Investigation -> the compact dict both the prompt and the
    MockLLM script (mock.py's `_consolidate`) read fields off of."""
    quote = inv.candidate.quote
    return {
        "id": inv.candidate.id,
        "category": inv.category,
        "secondary_category": inv.secondary_category,
        "confidence": inv.confidence,
        "occurrences": len(inv.candidate.occurrences),
        "quote": quote if len(quote) <= 80 else quote[:77] + "...",
        "evidence_titles": _evidence_titles(inv.evidence),
    }


def _user_prompt(compact: list[dict[str, Any]], rejected: int, needs_review: int) -> str:
    lines = ["CONFIRMED FINDINGS (id | category(+secondary) | confidence | "
             "occurrences | quote | evidence titles):"]
    for c in compact:
        secondary = f"+{c['secondary_category']}" if c["secondary_category"] else ""
        titles = ", ".join(c["evidence_titles"]) or "none"
        lines.append(
            f"{c['id']} | {c['category']}{secondary} | {c['confidence']} | "
            f"{c['occurrences']}x | \"{c['quote']}\" | {titles}"
        )
    lines.append("")
    lines.append(
        f"Context (not shown above, do not consolidate): {rejected} rejected, "
        f"{needs_review} confirmed-but-needs-human-review."
    )
    lines.append("")
    lines.append("Return ONLY the JSON object per the contract -- " + _CONTRACT)
    return "\n".join(lines)


def _try_parse(raw: str) -> dict[str, Any] | None:
    try:
        parsed = extract_json(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize(parsed: dict[str, Any], all_ids: list[str]) -> dict[str, Any]:
    """Enforce the invariants BUILD_PLAN R6 requires regardless of what the model
    returned: unknown ids are dropped, every real id ends up in kept or retracted
    (never silently lost), and a ambiguous kept+retracted id resolves to retracted."""
    valid_ids = set(all_ids)

    retracted = [
        {"id": r["id"], "rationale": str(r.get("rationale", ""))}
        for r in (parsed.get("retracted") or [])
        if isinstance(r, dict) and r.get("id") in valid_ids
    ]
    retracted_ids = {r["id"] for r in retracted}

    kept = [
        i for i in (parsed.get("kept") or [])
        if i in valid_ids and i not in retracted_ids  # retracted wins over kept
    ]
    present = set(kept) | retracted_ids
    for i in all_ids:  # never silently lose a finding
        if i not in present:
            kept.append(i)
            present.add(i)

    patterns = []
    for p in parsed.get("patterns") or []:
        if not isinstance(p, dict):
            continue
        finding_ids = [i for i in (p.get("finding_ids") or []) if i in valid_ids]
        if not finding_ids:
            continue
        patterns.append({
            "framing": str(p.get("framing", "")),
            "category": str(p.get("category", "")),
            "finding_ids": finding_ids,
        })

    summary = str(parsed.get("summary") or "").strip() or "Findings consolidated."
    return {
        "kept": kept, "retracted": retracted, "patterns": patterns,
        "summary": summary, "skipped": False,
    }


def consolidate(llm: Any, investigations: list[Investigation]) -> dict[str, Any]:
    """Run the ReportConsolidator over every CONFIRMED investigation (PRD §4 [4]).

    Rejected investigations never reach the model -- they died at verification and
    are passed only as a context count. Returns `_SKIPPED_RESULT` (zero LLM calls)
    when nothing confirmed. On an unparseable response (even after one repair
    retry), keeps every confirmed finding rather than dropping the report.
    """
    confirmed = [inv for inv in investigations if inv.verdict == "confirmed"]
    if not confirmed:
        return dict(_SKIPPED_RESULT)

    rejected = sum(1 for inv in investigations if inv.verdict != "confirmed")
    needs_review = sum(1 for inv in confirmed if inv.needs_human_review)
    compact = [_compact(inv) for inv in confirmed]
    all_ids = [c["id"] for c in compact]

    prompt = _user_prompt(compact, rejected, needs_review)
    call_kwargs = {"system": _SYSTEM, "task": "consolidate", "findings": compact,
                   "max_tokens": 1500}

    raw = llm.complete(prompt, **call_kwargs)
    parsed = _try_parse(raw)
    if parsed is None:
        retry_prompt = prompt + "\n\nReturn ONLY the JSON object, no prose."
        raw = llm.complete(retry_prompt, **call_kwargs)
        parsed = _try_parse(raw)
    if parsed is None:
        return {
            "kept": list(all_ids), "retracted": [], "patterns": [],
            "summary": "Consolidation response could not be parsed; all confirmed "
                       "findings were kept.",
            "skipped": False, "parse_failed": True,
        }
    return _normalize(parsed, all_ids)
