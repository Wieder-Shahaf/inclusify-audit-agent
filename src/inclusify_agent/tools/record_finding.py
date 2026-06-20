"""Tool: append a Finding to the running list (and emit an event for the trace)."""
from __future__ import annotations

from .schemas import Finding


def record_finding(findings: list[Finding], finding: Finding) -> list[Finding]:
    """Mutate the list in place AND return it (LangGraph-friendly)."""
    findings.append(finding)
    return findings
