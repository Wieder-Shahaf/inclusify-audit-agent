"""Report renderer: v2 pipeline state -> schema-validated JSON-serializable dict.

`pipeline.run_v2`'s merged state + `tools.consolidate`'s output -> the v2.0 report dict
(PRD §9): `version`, `language`, `summary`, `patterns[]`, `findings[]` (quote, offsets,
category, explanation, evidence[], rewrite, confidence, grounded, needs_human_review,
retracted).
"""
from __future__ import annotations

from typing import Any

VALID_CONFIDENCE = {"low", "medium", "high"}


class ReportSchemaError(ValueError):
    """Raised when the rendered report doesn't satisfy the schema."""


REPORT_VERSION_V2 = "2.0"
_SNIPPET_CAP = 300


def _evidence_to_dict_v2(e: dict[str, Any]) -> dict[str, Any]:
    """One investigator-evidence dict (`{id, text, score, metadata, n}`, from
    `tools.investigate._citation_dict`) -> the v2 report's evidence shape."""
    meta = e.get("metadata") or {}
    text = str(e.get("text", "") or "")
    return {
        "title": str(meta.get("title", "")),
        "year": meta.get("year"),
        "url": str(meta.get("url", "")),
        "snippet": text[:_SNIPPET_CAP],
        "score": float(e.get("score", 0.0)),
        "source": str(meta.get("source", "")),
    }


def _finding_to_dict_v2(
    investigation: Any, *, retracted: bool, retraction_rationale: str | None,
) -> dict[str, Any]:
    candidate = investigation.candidate
    evidence = [_evidence_to_dict_v2(e) for e in investigation.evidence]
    return {
        "id": candidate.id,
        "quote": candidate.quote,
        "offsets": [candidate.char_start, candidate.char_end],
        "occurrences": len(candidate.occurrences),
        "category": investigation.category,
        "secondary_category": investigation.secondary_category,
        "explanation": investigation.explanation,
        "evidence": evidence,
        "rewrite": investigation.rewrite,
        "confidence": investigation.confidence,
        "grounded": bool(evidence),
        "needs_human_review": investigation.needs_human_review,
        "retracted": retracted,
        "retraction_rationale": retraction_rationale,
    }


def render_v2(v2_result: dict[str, Any], consolidation: dict[str, Any]) -> dict[str, Any]:
    """`pipeline.run_v2`'s merged state + `tools.consolidate`'s output -> the v2.0
    report dict (PRD §9). Rejected investigations never become findings -- they
    died at verification and are counted only, in `summary`.

    Findings are ordered kept-first in the consolidator's own severity order, then
    retracted findings last (PRD §9 / BUILD_PLAN R6 spec) -- never MockLLM/live
    model ordering left to chance.
    """
    investigations: list[Any] = v2_result.get("investigations", [])
    by_id = {inv.candidate.id: inv for inv in investigations}

    retracted_list = consolidation.get("retracted", [])
    rationale_by_id = {r["id"]: r["rationale"] for r in retracted_list if r["id"] in by_id}
    kept_ids = [i for i in consolidation.get("kept", []) if i in by_id]
    retracted_ids = [
        r["id"] for r in retracted_list if r["id"] in by_id and r["id"] not in kept_ids
    ]

    findings = [
        _finding_to_dict_v2(by_id[fid], retracted=False, retraction_rationale=None)
        for fid in kept_ids
    ] + [
        _finding_to_dict_v2(by_id[fid], retracted=True, retraction_rationale=rationale_by_id[fid])
        for fid in retracted_ids
    ]

    stats = v2_result.get("stats", {})
    summary = {
        "windows": stats.get("windows", 0),
        "candidates": stats.get("candidates", 0),
        "confirmed": stats.get("confirmed", 0),
        "rejected": stats.get("rejected", 0),
        "retracted": len(retracted_ids),
        "needs_human_review": stats.get("needs_human_review", 0),
        "patterns": len(consolidation.get("patterns", [])),
    }
    return {
        "version": REPORT_VERSION_V2,
        "language": "en",
        "summary": summary,
        "patterns": consolidation.get("patterns", []),
        "findings": findings,
    }


def validate_v2(report: dict[str, Any]) -> None:
    """Structural validation for the v2.0 report: raises `ReportSchemaError` on the
    first violation, checked recursively through summary / patterns / findings / evidence."""
    if not isinstance(report, dict):
        raise ReportSchemaError("report must be a dict")
    for key in ("version", "language", "summary", "patterns", "findings"):
        if key not in report:
            raise ReportSchemaError(f"missing top-level key: {key}")
    if report["version"] != REPORT_VERSION_V2:
        raise ReportSchemaError(f"version must be {REPORT_VERSION_V2!r}")

    summary = report["summary"]
    if not isinstance(summary, dict):
        raise ReportSchemaError("summary must be a dict")
    for key in ("windows", "candidates", "confirmed", "rejected", "retracted",
                "needs_human_review", "patterns"):
        if key not in summary:
            raise ReportSchemaError(f"summary missing key: {key}")

    if not isinstance(report["patterns"], list):
        raise ReportSchemaError("patterns must be a list")
    for p in report["patterns"]:
        for key in ("framing", "category", "finding_ids"):
            if key not in p:
                raise ReportSchemaError(f"pattern missing key: {key}")

    if not isinstance(report["findings"], list):
        raise ReportSchemaError("findings must be a list")
    for f in report["findings"]:
        for key in ("id", "quote", "offsets", "occurrences", "category",
                    "secondary_category", "explanation", "evidence", "rewrite",
                    "confidence", "grounded", "needs_human_review", "retracted",
                    "retraction_rationale"):
            if key not in f:
                raise ReportSchemaError(f"finding missing key: {key}")
        if not (isinstance(f["offsets"], (list, tuple)) and len(f["offsets"]) == 2):
            raise ReportSchemaError(f"finding {f.get('id')!r} offsets must be a [start, end] pair")
        if f["confidence"] not in VALID_CONFIDENCE:
            raise ReportSchemaError(f"invalid confidence: {f['confidence']!r}")
        if not isinstance(f["evidence"], list):
            raise ReportSchemaError(f"finding {f.get('id')!r} evidence must be a list")
        for e in f["evidence"]:
            for key in ("title", "year", "url", "snippet", "score", "source"):
                if key not in e:
                    raise ReportSchemaError(f"evidence missing key: {key}")


def to_markdown_v2(report: dict[str, Any]) -> str:
    """Human-readable v2 rendering: doc summary line, patterns section (if any),
    per-finding Why/Evidence/rewrite/confidence, and a final retracted section.
    A clean document (nothing confirmed) gets a clear one-line verdict instead."""
    summary = report["summary"]
    kept = [f for f in report["findings"] if not f["retracted"]]
    retracted = [f for f in report["findings"] if f["retracted"]]

    lines: list[str] = ["# Inclusify audit report (v2)\n"]
    lines.append(
        f"**Windows:** {summary['windows']} · **Candidates:** {summary['candidates']} · "
        f"**Confirmed:** {summary['confirmed']} · **Rejected:** {summary['rejected']} · "
        f"**Retracted:** {summary['retracted']} · "
        f"**Needs human review:** {summary['needs_human_review']}\n"
    )

    if not kept:
        lines.append("\nNo inclusivity issues were confirmed in this document.\n")
        return "".join(lines)

    if report.get("patterns"):
        lines.append("\n## Recurring patterns\n")
        for p in report["patterns"]:
            lines.append(
                f"- **{p['framing']}** ({p['category']}) — {len(p['finding_ids'])} findings\n"
            )

    lines.append("\n## Findings\n")
    for n, f in enumerate(kept, start=1):
        secondary = f" / {f['secondary_category']}" if f.get("secondary_category") else ""
        lines.append(f"\n### {n}. [{f['category']}{secondary}] \"{f['quote']}\"\n")
        lines.append(f"\n**Why:** {f['explanation']}\n")
        if f["evidence"]:
            lines.append("\n**Evidence:**\n")
            for e in f["evidence"]:
                title = e.get("title") or "(untitled)"
                year = f" ({e['year']})" if e.get("year") else ""
                url = f" — {e['url']}" if e.get("url") else ""
                lines.append(f"- {title}{year}{url}\n")
        else:
            lines.append("\n**Evidence:** none retrieved (ungrounded)\n")
        if f.get("rewrite"):
            lines.append(f"\n**Suggested rewrite:** {f['rewrite']!r}\n")
        flags = f"confidence={f['confidence']}"
        if f["needs_human_review"]:
            flags += ", needs human review"
        lines.append(f"\n_{flags}_\n")

    if retracted:
        lines.append("\n## Retracted during review\n")
        for f in retracted:
            lines.append(
                f"\n- [{f['category']}] \"{f['quote']}\" — {f.get('retraction_rationale', '')}\n"
            )

    return "".join(lines)
