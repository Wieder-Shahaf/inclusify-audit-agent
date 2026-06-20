"""Fixed-pipeline baseline (no autonomy).

The agent owns its control flow; this baseline runs a hard-coded sequence:
chunk -> lexicon_lookup -> classify -> record. No retrieval, no reflection,
no asking — every flagged span is recorded as-is. The trace is the linear
sequence; no `ask` or `retract` events.

This is what the agent must DIVERGE from to prove its autonomy is doing work
(BUILD_PLAN §6, P7 exit).
"""
from __future__ import annotations

import uuid
from typing import Any

from inclusify_agent.tools import chunk, classify_span, lexicon_lookup, record_finding
from inclusify_agent.tools.schemas import Finding


def run_baseline(text: str, *, llm: Any) -> dict[str, Any]:
    """Return {findings: [Finding], trace: [event]}."""
    findings: list[Finding] = []
    trace: list[dict[str, Any]] = []

    chunks = chunk(text)
    trace.append({"node": "baseline", "tool": "chunk", "detail": {"chunk_count": len(chunks)}})

    for c in chunks:
        hits = lexicon_lookup(c)
        trace.append({"node": "baseline", "tool": "lexicon_lookup",
                      "chunk_id": c.id, "detail": {"hits": len(hits)}})
        if not hits:
            continue
        result = classify_span(llm, span=c.text)
        trace.append({"node": "baseline", "tool": "classify_span",
                      "chunk_id": c.id, "detail": result})
        if result.get("label") == "flag":
            f = Finding(
                id=str(uuid.uuid4())[:8],
                chunk_id=c.id,
                span=c.text,
                label="flag",
                category=result.get("category"),
                reason=result.get("reason", ""),
                confidence="medium",
            )
            record_finding(findings, f)
            trace.append({"node": "baseline", "tool": "record_finding",
                          "chunk_id": c.id, "detail": {"finding_id": f.id}})

    return {"findings": findings, "trace": trace}
