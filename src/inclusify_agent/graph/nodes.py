"""LangGraph nodes for the Inclusify audit agent.

Each node is a pure function: AgentState → AgentState (partial update). LangGraph merges
the update into the running state.

Design: the LLM owns the control flow via the route node. The route node calls
MockLLM (or live LLM) with task="route" to choose the next tool; the act node
executes that tool. This is the ReAct loop. The reflect node runs once before stop
to drop low-confidence findings — that produces the `retract` event in the trace.

The agentic-RAG retract-if-ungrounded path: when retrieve_citation returns nothing
or the LLM 'ground' check fails, the finding is created with grounded=False and
reflect retracts it (or routes to ask_user).
"""
from __future__ import annotations

import json
import uuid
from typing import Any

from ..tools import (
    ask_user,
    chunk,
    classify_span,
    lexicon_lookup,
    propose_rewrite,
    record_finding,
    retrieve_citation,
)
from ..tools.schemas import Citation, Finding
from .state import AgentState, TraceEvent


def _emit(state: AgentState, **event: Any) -> list[TraceEvent]:
    """Append a TraceEvent and return the updated trace list."""
    trace = list(state.get("trace", []))
    event.setdefault("step", state.get("step", 0))
    trace.append(event)
    return trace


def perceive(state: AgentState) -> dict[str, Any]:
    """Initial chunking + state prime."""
    chunks = chunk(state.get("document_text", ""))
    trace = _emit(state, node="perceive", detail={"chunk_count": len(chunks)})
    return {
        "chunks": chunks,
        "current_chunk_idx": 0,
        "findings": state.get("findings", []),
        "trace": trace,
        "step": state.get("step", 0) + 1,
        "next_action": "lexicon_lookup",
    }


def route(state: AgentState, *, llm: Any) -> dict[str, Any]:
    """The LLM decides the next tool. Bounded by max_iters.

    Strategy: act() proposes a 'next_action' based on tool output; route asks the LLM
    to confirm or override. The LLM sees the last-run tool + its outcome and picks
    the next step. This is the ReAct election point — the LLM owns control flow.

    Override safety: if act() set next_action = "reflect" or "stop" (chunk-list
    exhausted), route honors that directly (terminal phase, no LLM needed).
    """
    step = state.get("step", 0)
    max_iters = state.get("max_iters", 12)
    proposed = state.get("next_action", "lexicon_lookup")

    # Bound: at max_iters, force reflect (once), then stop. This way the trace always
    # carries a reflect event even for documents that hit the iteration cap.
    if step >= max_iters:
        already_reflected = any(
            ev.get("node") == "reflect" for ev in state.get("trace", [])
        )
        target = "stop" if already_reflected else "reflect"
        return {
            "next_action": target,
            "trace": _emit(state, node="route", rationale="max_iters reached", tool=target),
            "step": step + 1,
        }

    # Terminal proposals from act/perceive (no LLM call needed).
    if proposed in ("reflect", "stop"):
        return {
            "next_action": proposed,
            "trace": _emit(state, node="route", tool=proposed, rationale="terminal proposal"),
            "step": step + 1,
        }

    chunks = state.get("chunks", [])
    idx = state.get("current_chunk_idx", 0)
    if idx >= len(chunks):
        return {
            "next_action": "reflect",
            "trace": _emit(state, node="route", tool="reflect", rationale="all chunks processed"),
            "step": step + 1,
        }

    # Ask the LLM. The hint carries what act() just proposed; MockLLM follows
    # the scripted ReAct sequence; a real LLM can override.
    last_ran = state.get("_last_tool_ran", "perceive")
    hint = (
        f"chunk_idx={idx}/{len(chunks)}; "
        f"last_action={last_ran}; "
        f"proposed={proposed}; "
        f"findings={len(state.get('findings', []))}"
    )
    raw = llm.complete("route?", task="route", step=step, state_hint=hint)
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {"tool": proposed, "rationale": "default (parse fail)"}
    tool = decision.get("tool", proposed)
    rationale = decision.get("rationale", "")
    # Safety: if the LLM picks an unknown action, fall back to the proposal.
    valid = {"lexicon_lookup", "classify_span", "retrieve_citation",
             "propose_rewrite", "ask_user", "reflect", "stop"}
    if tool not in valid:
        tool = proposed
        rationale = f"fallback to proposed (LLM picked unknown: {decision.get('tool')})"
    return {
        "next_action": tool,
        "trace": _emit(state, node="route", tool=tool, rationale=rationale),
        "step": step + 1,
    }


def act(state: AgentState, *, llm: Any, store: Any, embedder: Any) -> dict[str, Any]:
    """Execute the chosen tool against the current chunk."""
    action = state.get("next_action", "lexicon_lookup")
    chunks = state.get("chunks", [])
    idx = state.get("current_chunk_idx", 0)
    if idx >= len(chunks):
        return {"step": state.get("step", 0) + 1, "next_action": "reflect"}
    cur = chunks[idx]
    step = state.get("step", 0)
    trace = list(state.get("trace", []))
    update: dict[str, Any] = {"step": step + 1, "_last_tool_ran": action}

    if action == "lexicon_lookup":
        hits = lexicon_lookup(cur)
        trace.append({"step": step, "node": "act", "tool": "lexicon_lookup",
                      "chunk_id": cur.id, "detail": {"hits": len(hits)}})
        update["last_lexicon_hits"] = hits
        # Always escalate to classify_span. The lexicon catches obvious cases as a
        # cheap precision shortcut (high-confidence flags get the canonical
        # rewrite from the lexicon's alternatives); but the LLM must still judge
        # every span, because subtle bias has no lexicon trigger and clean text
        # ABOUT inclusive topics shouldn't be flagged just for the topic.
        update["next_action"] = "classify_span"

    elif action == "classify_span":
        result = classify_span(llm, span=cur.text, context=cur.context_before)
        trace.append({"step": step, "node": "act", "tool": "classify_span",
                      "chunk_id": cur.id, "detail": result})
        update["last_classification"] = result
        label = result.get("label")
        if label == "flag":
            update["next_action"] = "retrieve_citation"
        elif label == "ask":
            update["next_action"] = "ask_user"
        else:
            # Skip this chunk; advance to the next one.
            update["current_chunk_idx"] = idx + 1
            update["next_action"] = "lexicon_lookup"

    elif action == "retrieve_citation":
        hits = state.get("last_lexicon_hits") or []
        query = hits[0].term if hits else cur.text[:80]
        cites = retrieve_citation(store, embedder, query=query, k=3)
        trace.append({"step": step, "node": "act", "tool": "retrieve_citation",
                      "chunk_id": cur.id, "detail": {"k": len(cites)}})
        update["last_citations"] = cites
        # Agentic-RAG: when retrieval is weak (top score below threshold), the
        # flag is unverified — route to ask_user instead of finalizing a rewrite.
        # MockLLM emits cosine-like scores; 0.3 is a generous floor.
        if cites and cites[0].score >= 0.3:
            update["next_action"] = "propose_rewrite"
        else:
            update["next_action"] = "ask_user"

    elif action == "propose_rewrite":
        cls = state.get("last_classification") or {"category": None}
        lex_hits = state.get("last_lexicon_hits") or []
        rewrite_out = propose_rewrite(
            llm, span=cur.text, category=cls.get("category"), lexicon_hits=lex_hits,
        )
        trace.append({"step": step, "node": "act", "tool": "propose_rewrite",
                      "chunk_id": cur.id, "detail": rewrite_out})
        update["last_rewrite"] = rewrite_out
        # Build a finding from accumulated state.
        finding = _build_finding(cur, state, rewrite_out)
        findings = list(state.get("findings", []))
        record_finding(findings, finding)
        update["findings"] = findings
        # Advance to the next chunk.
        update["current_chunk_idx"] = idx + 1
        update["next_action"] = "lexicon_lookup"

    elif action == "ask_user":
        cls = state.get("last_classification") or {}
        q = f"Is '{cur.text}' appropriate in context? (reason: {cls.get('reason', '')})"
        out = ask_user(q, mode="auto", default_answer="unknown")
        trace.append({"step": step, "node": "act", "tool": "ask_user",
                      "chunk_id": cur.id, "detail": out})
        update["last_question"] = out
        # Record an 'asked' finding (label=ask).
        findings = list(state.get("findings", []))
        findings.append(Finding(
            id=str(uuid.uuid4())[:8],
            chunk_id=cur.id,
            span=cur.text,
            label="ask",
            category=cls.get("category"),
            reason=cls.get("reason", "needs clarification"),
            confidence="low",
            asked=True,
        ))
        update["findings"] = findings
        update["current_chunk_idx"] = idx + 1
        update["next_action"] = "lexicon_lookup"

    else:
        # Unknown action — bail by advancing.
        trace.append({"step": step, "node": "act", "tool": action,
                      "chunk_id": cur.id, "detail": {"error": "unknown action"}})
        update["next_action"] = "stop"

    update["trace"] = trace
    return update


def _build_finding(cur: Any, state: AgentState, rewrite_out: dict[str, Any]) -> Finding:
    """Assemble a Finding from the accumulated state at the end of a chunk's act."""
    cls = state.get("last_classification") or {}
    cites = state.get("last_citations") or []
    grounded = bool(cites)
    citation_obj: Citation | None = cites[0] if cites else None
    # Confidence rule: high when citation is strong; low when weak/missing (reflect
    # retracts); medium in between. Thresholds tuned to live BGE-M3 cosine scores
    # (the hash embedder produces a wider range; both work).
    top_score = cites[0].score if cites else 0.0
    if top_score >= 0.5:
        confidence = "high"
    elif top_score < 0.35:
        confidence = "low"
    else:
        confidence = "medium"
    return Finding(
        id=str(uuid.uuid4())[:8],
        chunk_id=cur.id,
        span=cur.text,
        label=cls.get("label", "flag"),
        category=cls.get("category"),
        reason=cls.get("reason", ""),
        confidence=confidence,  # type: ignore[arg-type]
        rewrite=rewrite_out.get("rewrite"),
        citation=citation_obj,
        grounded=grounded,
    )


def reflect(state: AgentState, *, llm: Any) -> dict[str, Any]:
    """LLM reflection: drop low-confidence findings; tag the retract events."""
    findings = list(state.get("findings", []))
    # Hand the LLM a serialized view so MockLLM can deterministically pick.
    serialized = [
        {"id": f.id, "confidence": f.confidence, "label": f.label}
        for f in findings
    ]
    raw = llm.complete("reflect", task="reflect", findings=serialized)
    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        decision = {"kept": serialized, "retracted": []}
    retracted_ids = set(decision.get("retracted", []))
    for f in findings:
        if f.id in retracted_ids:
            f.retracted = True
    step = state.get("step", 0)
    trace = _emit(state, node="reflect", detail={
        "retracted_ids": sorted(retracted_ids), "kept_count": len(findings) - len(retracted_ids),
    })
    return {
        "findings": findings,
        "trace": trace,
        "step": step + 1,
        "next_action": "stop",
    }


def stop(state: AgentState) -> dict[str, Any]:
    """Terminal node: emit a final trace event."""
    trace = _emit(state, node="stop", detail={
        "findings_total": len(state.get("findings", [])),
        "retracted": sum(1 for f in state.get("findings", []) if f.retracted),
        "asked": sum(1 for f in state.get("findings", []) if f.asked),
    })
    return {"trace": trace, "step": state.get("step", 0) + 1, "next_action": "stop"}
