"""Report renderer: AgentState -> schema-validated JSON-serializable dict.

Schema (declared as a JSON Schema-ish dict so we can validate at the boundary):

  {
    "version": "1.0",
    "document": {"text_chars": int},
    "findings": [{
        "id": str, "chunk_id": str, "span": str,
        "label": "flag"|"ask"|"skip", "category": str|null,
        "reason": str, "confidence": "low"|"medium"|"high",
        "rewrite": str|null,
        "citation": {"id": str, "text": str, "score": float, "url": str}|null,
        "grounded": bool, "asked": bool, "retracted": bool,
    }, ...],
    "stats": {"findings_total": int, "retracted": int, "asked": int, "grounded": int},
    "trace": [{"step": int, "node": str, "tool": str|None, "chunk_id": str|None,
               "detail": Any, "rationale": str}],
  }
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

REPORT_VERSION = "1.0"
VALID_LABELS = {"flag", "ask", "skip"}
VALID_CONFIDENCE = {"low", "medium", "high"}


def _citation_to_dict(c: Any) -> dict[str, Any] | None:
    if c is None:
        return None
    if is_dataclass(c):
        d = asdict(c)
    elif isinstance(c, dict):
        d = c
    else:
        return None
    return {
        "id": str(d.get("id", "")),
        "text": str(d.get("text", "")),
        "score": float(d.get("score", 0.0)),
        "url": str(d.get("metadata", {}).get("url", "")),
    }


def _finding_to_dict(f: Any) -> dict[str, Any]:
    d = asdict(f) if is_dataclass(f) else dict(f)
    return {
        "id": str(d.get("id", "")),
        "chunk_id": str(d.get("chunk_id", "")),
        "span": str(d.get("span", "")),
        "label": d.get("label", "skip"),
        "category": d.get("category"),
        "reason": d.get("reason", ""),
        "confidence": d.get("confidence", "medium"),
        "rewrite": d.get("rewrite"),
        "citation": _citation_to_dict(d.get("citation")),
        "grounded": bool(d.get("grounded", False)),
        "asked": bool(d.get("asked", False)),
        "retracted": bool(d.get("retracted", False)),
    }


def render(state: dict[str, Any]) -> dict[str, Any]:
    """Convert a final AgentState dict into the report shape."""
    findings = [_finding_to_dict(f) for f in state.get("findings", [])]
    trace = list(state.get("trace", []))
    text = state.get("document_text", "")
    return {
        "version": REPORT_VERSION,
        "document": {"text_chars": len(text)},
        "findings": findings,
        "stats": {
            "findings_total": len(findings),
            "retracted": sum(1 for f in findings if f["retracted"]),
            "asked": sum(1 for f in findings if f["asked"]),
            "grounded": sum(1 for f in findings if f["grounded"]),
        },
        "trace": trace,
    }


class ReportSchemaError(ValueError):
    """Raised when the rendered report doesn't satisfy the schema."""


def validate(report: dict[str, Any]) -> None:
    """Structural validation. Raises ReportSchemaError on first violation."""
    if not isinstance(report, dict):
        raise ReportSchemaError("report must be a dict")
    for key in ("version", "document", "findings", "stats", "trace"):
        if key not in report:
            raise ReportSchemaError(f"missing top-level key: {key}")
    if report["version"] != REPORT_VERSION:
        raise ReportSchemaError(f"version must be {REPORT_VERSION!r}")
    if not isinstance(report["findings"], list):
        raise ReportSchemaError("findings must be a list")
    if not isinstance(report["trace"], list):
        raise ReportSchemaError("trace must be a list")
    for f in report["findings"]:
        for key in ("id", "chunk_id", "span", "label", "reason", "confidence",
                    "grounded", "asked", "retracted"):
            if key not in f:
                raise ReportSchemaError(f"finding missing key: {key}")
        if f["label"] not in VALID_LABELS:
            raise ReportSchemaError(f"invalid label: {f['label']!r}")
        if f["confidence"] not in VALID_CONFIDENCE:
            raise ReportSchemaError(f"invalid confidence: {f['confidence']!r}")
    stats = report["stats"]
    if not isinstance(stats, dict):
        raise ReportSchemaError("stats must be a dict")
    for key in ("findings_total", "retracted", "asked", "grounded"):
        if key not in stats:
            raise ReportSchemaError(f"stats missing key: {key}")


def to_markdown(report: dict[str, Any]) -> str:
    """Render a human-readable markdown summary alongside the JSON."""
    lines: list[str] = ["# Inclusify audit report\n"]
    stats = report["stats"]
    lines.append(
        f"**Document:** {report['document']['text_chars']} chars · "
        f"**Findings:** {stats['findings_total']} "
        f"(grounded={stats['grounded']}, asked={stats['asked']}, "
        f"retracted={stats['retracted']})\n"
    )
    for f in report["findings"]:
        marker = {"flag": "FLAG", "ask": "ASK ", "skip": "SKIP"}.get(f["label"], "????")
        retracted = " (RETRACTED)" if f["retracted"] else ""
        lines.append(
            f"\n- **{marker}** [{f['confidence']}] {f['span']!r}{retracted}\n"
            f"  - category: {f['category']}\n"
            f"  - reason: {f['reason']}\n"
        )
        if f.get("rewrite"):
            lines.append(f"  - suggested rewrite: {f['rewrite']!r}\n")
        if f.get("citation"):
            c = f["citation"]
            lines.append(f"  - citation: {c['id']} (score={c['score']:.3f}) {c['text'][:120]!r}\n")
    return "".join(lines)
