"""LangGraph state for the Inclusify audit agent.

State is a TypedDict — LangGraph requires this for graph compilation. Lists are
explicitly typed so reducers (LangGraph) can append cleanly across nodes.
"""
from __future__ import annotations

from typing import Any, TypedDict

from ..tools.schemas import Chunk, Citation, Finding, LexiconHit


class TraceEvent(TypedDict, total=False):
    """One event in the decision trace."""
    step: int
    node: str         # "perceive" | "route" | "act" | "observe" | "reflect" | "stop"
    tool: str         # tool name if node=="act"
    chunk_id: str
    detail: Any       # tool-specific payload
    rationale: str


class AgentState(TypedDict, total=False):
    """The mutable state passed through the graph."""
    # Input
    document_text: str

    # Working memory
    chunks: list[Chunk]
    current_chunk_idx: int

    # Tool outputs (latest)
    last_lexicon_hits: list[LexiconHit]
    last_classification: dict[str, Any]
    last_citations: list[Citation]
    last_rewrite: dict[str, Any]
    last_question: dict[str, Any]

    # Accumulators
    findings: list[Finding]
    trace: list[TraceEvent]

    # Loop control
    step: int
    max_iters: int
    next_action: str  # one of: lexicon_lookup, classify_span, retrieve_citation,
                      #         propose_rewrite, ask_user, reflect, stop
    _last_tool_ran: str
