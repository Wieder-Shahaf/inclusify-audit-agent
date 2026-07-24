"""Tool: the v2 EvidenceInvestigator tool loop, per candidate (PRD §4 [3], BUILD_PLAN R5).

JSON-action protocol rather than native tool-calls (PRD §12 risk: LLMod's tool-call
passthrough is unverified) -- the model replies with exactly one JSON action object
per turn (`corpus_search` / `live_search` / `finalize`); this keeps `steps[]` the same
shape whether or not a provider's native tool-calling ends up working.

`LLMProvider.complete` is single-prompt (no chat history), so each turn is a fresh,
stateless re-prompt: the candidate block, every evidence citation seen so far
(numbered, continuing across turns), and the actions already taken are all rebuilt
into one user prompt every time. Simple, provider-agnostic, and easy to trace.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Callable

from ._json_extract import extract_json
from .audit_window import _normalize_category
from .schemas import Citation

_INVALID_NOTE = "Your last reply was not a valid action."
_LIVE_UNAVAILABLE_NOTE = (
    "live_search is not available for this run; choose corpus_search or finalize."
)
_MAX_SNIPPET = 400

# The exact per-turn action contract -- stated once in `_SYSTEM` below, then repeated
# verbatim (via `_user_prompt`) as a reminder on every turn.
_CONTRACT = (
    "Reply with ONLY ONE JSON object per turn, no prose, no markdown fences:\n"
    '{"action": "corpus_search", "query": "<your search query>"}\n'
    '{"action": "live_search", "phrases": ["..."], "any_of": ["..."], "min_year": 2010}\n'
    '{"action": "finalize", "verdict": "confirmed"|"rejected", "category": "<one of '
    'the 7>", "secondary_category": null|"<one of the 7>", "explanation": "2-4 '
    'sentences citing evidence as [1],[2]", "rewrite": "<minimal-edit inclusive '
    'rewrite of the SENTENCE>", "confidence": "high"|"medium"|"low", '
    '"needs_human_review": true|false, "evidence_used": [1]}'
)

# ONE constant (KV-cache): all variable content (candidate, evidence, history) lives
# in the user prompt built by `_user_prompt`, never here.
_SYSTEM = (
    "You are an evidence investigator for an inclusivity audit of English academic "
    "text. You receive ONE candidate finding -- a quoted span, its category, the "
    "reason it was flagged, its sentence and surrounding paragraph, and lexicon "
    "alternatives if any exist. Over a few turns, decide what evidence would confirm "
    "or refute this finding, call tools to get that evidence, then give a verdict.\n\n"
    "corpus_search runs a semantic search over the ERIC academic-inclusivity corpus. "
    "live_search instead walks the live ERIC API ladder (ONLY when the user turn "
    "says it's available). finalize gives your verdict.\n\n"
    + _CONTRACT + "\n\n"
    'Rules: verdict "rejected" means the span is actually fine in its context -- '
    'explain why, and set rewrite to "". Cite evidence indices like [1] and [2] in '
    "the explanation whenever the verdict is confirmed and evidence exists. Prefer "
    "the candidate's own lexicon alternatives in your rewrite when they fit. "
    "Confidence: high = strong directly-relevant evidence, medium = related "
    "evidence, low = weak or no evidence. If evidence stays weak after searching, "
    "still give an honest verdict and set needs_human_review to true rather than "
    "stalling."
)


def _candidate_block(ctx: dict[str, Any]) -> str:
    alts = ", ".join(ctx.get("alternatives") or []) or "none"
    return (
        "CANDIDATE FINDING:\n"
        f'Quote: "{ctx["quote"]}"\n'
        f"Category: {ctx.get('category', '')}\n"
        f"Reason: {ctx.get('reason', '')}\n"
        f"Sentence: {ctx.get('sentence_text', '')}\n"
        f"Paragraph: {ctx.get('paragraph_text', '')}\n"
        f"Lexicon alternatives: {alts}\n"
        f"Occurrences in document so far: {ctx.get('occurrences_count', 1)}"
    )


def _evidence_block(evidence: list[Citation]) -> str:
    if not evidence:
        return ""
    lines = ["EVIDENCE SO FAR:"]
    for i, c in enumerate(evidence, start=1):
        meta = c.metadata or {}
        lines.append(
            f"[{i}] {meta.get('title', '')} ({meta.get('year', '')}) "
            f"score={c.score:.2f} {meta.get('url', '')}"
        )
        lines.append(c.text[:_MAX_SNIPPET])
    return "\n".join(lines)


def _user_prompt(
    ctx: dict[str, Any],
    evidence: list[Citation],
    actions_taken: list[str],
    live_available: bool,
    notes: list[str],
) -> str:
    """Rebuild the FULL user prompt every turn (stateless re-prompt, see module
    docstring) -- candidate block + evidence so far + actions so far + any note from
    an invalid previous reply + the action contract reminder."""
    parts = [_candidate_block(ctx)]
    evidence_block = _evidence_block(evidence)
    if evidence_block:
        parts.append(evidence_block)
    parts.append(f"Previous actions: {actions_taken}")
    parts.append(f"Live search available: {'yes' if live_available else 'no'}")
    parts.extend(notes)
    parts.append(_CONTRACT)
    return "\n\n".join(parts)


def _try_parse_action(raw: str) -> dict[str, Any] | None:
    try:
        parsed = extract_json(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _citation_dict(n: int, citation: Citation) -> dict[str, Any]:
    d = asdict(citation)
    d["n"] = n
    return d


def _dedupe_add(evidence: list[Citation], seen_ids: set[str], new: list[Citation]) -> None:
    for c in new:
        if c.id in seen_ids:
            continue
        seen_ids.add(c.id)
        evidence.append(c)


def _finalize_result(
    action: dict[str, Any],
    evidence: list[Citation],
    actions_taken: list[str],
    turns: int,
) -> dict[str, Any]:
    secondary_raw = action.get("secondary_category")
    confidence = action.get("confidence")
    verdict = action.get("verdict")
    return {
        # Conservative default: an unparseable/unexpected verdict does not claim
        # "confirmed" on the model's behalf.
        "verdict": verdict if verdict in ("confirmed", "rejected") else "rejected",
        "category": _normalize_category(action.get("category")),
        "secondary_category": _normalize_category(secondary_raw) if secondary_raw else None,
        "explanation": str(action.get("explanation") or ""),
        "rewrite": str(action.get("rewrite") or ""),
        "confidence": confidence if confidence in ("high", "medium", "low") else "low",
        "needs_human_review": bool(action.get("needs_human_review", False)),
        "evidence": [_citation_dict(i, c) for i, c in enumerate(evidence, start=1)],
        "evidence_used": action.get("evidence_used") or [],
        "turns": turns,
        "actions": list(actions_taken),
        "forced": False,
    }


def _forced_result(
    candidate_ctx: dict[str, Any],
    evidence: list[Citation],
    actions_taken: list[str],
    turns: int,
) -> dict[str, Any]:
    """Turn budget exhausted without a `finalize` action -- force one (PRD §4 [3] /
    BUILD_PLAN R5's hard turn bound). Confirmed + low confidence + needs_human_review:
    an unresolved candidate stays visible to a human rather than silently vanishing."""
    return {
        "verdict": "confirmed",
        "category": _normalize_category(candidate_ctx.get("category")),
        "secondary_category": None,
        "explanation": (
            f"{candidate_ctx.get('reason', '')} "
            "(verification incomplete: investigator hit its turn limit)"
        ),
        "rewrite": "",
        "confidence": "low",
        "needs_human_review": True,
        "evidence": [_citation_dict(i, c) for i, c in enumerate(evidence, start=1)],
        "evidence_used": [],
        "turns": turns,
        "actions": list(actions_taken),
        "forced": True,
    }


def investigate(
    llm: Any,
    candidate_ctx: dict[str, Any],
    *,
    corpus_search: Callable[[str], list[Citation]],
    live_search: Callable[..., list[Citation]] | None = None,
    max_turns: int = 4,
) -> dict[str, Any]:
    """Run the EvidenceInvestigator tool loop for ONE candidate finding (PRD §4 [3]).

    `candidate_ctx`: dict with quote, category, reason, sentence_text, paragraph_text,
    alternatives (list), occurrences_count. `corpus_search`/`live_search` are the only
    ways this function touches the world; `live_search=None` means it isn't wired up
    for this run (env-gated upstream) and is never advertised or executed.

    Never raises. Each reply is parsed with `extract_json`; a parse failure gets ONE
    repair retry within the SAME turn (the `turn` counter, and the MockLLM script
    keyed on it, only advance on genuinely new turns). An unrecognized action name,
    JSON that still won't parse after the repair, or a `live_search` request when none
    is wired, all downgrade to "not a valid action" -- the turn is spent, and the next
    prompt carries a note asking the model to try again. Running out of turns without
    a `finalize` forces one (see `_forced_result`).
    """
    evidence: list[Citation] = []
    seen_ids: set[str] = set()
    actions_taken: list[str] = []
    notes: list[str] = []
    live_available = live_search is not None
    turns = 0

    for turn in range(1, max_turns + 1):
        turns = turn
        prompt = _user_prompt(candidate_ctx, evidence, actions_taken, live_available, notes)
        notes = []  # last turn's notes just went into `prompt`; this turn accumulates its own
        top_score = max((c.score for c in evidence), default=0.0)
        call_kwargs = {
            "system": _SYSTEM,
            "task": "investigate",
            "turn": turn,
            "candidate_quote": candidate_ctx.get("quote", ""),
            "category": candidate_ctx.get("category", ""),
            "top_score": top_score,
            "live_available": live_available,
        }

        raw = llm.complete(prompt, **call_kwargs)
        action = _try_parse_action(raw)
        if action is None:
            raw = llm.complete(prompt + "\n\nReturn ONLY the JSON action object.", **call_kwargs)
            action = _try_parse_action(raw)

        name = action.get("action") if action else None

        if name == "finalize":
            actions_taken.append("finalize")
            return _finalize_result(action, evidence, actions_taken, turns)

        if name == "corpus_search":
            actions_taken.append("corpus_search")
            query = str(action.get("query") or "")
            try:
                new_evidence = corpus_search(query)
            except Exception:  # ponytail: a flaky tool degrades to "no new evidence", never aborts
                new_evidence = []
            _dedupe_add(evidence, seen_ids, new_evidence)
            continue

        if name == "live_search":
            if not live_available:
                actions_taken.append("invalid")
                notes.append(_LIVE_UNAVAILABLE_NOTE)
                continue
            actions_taken.append("live_search")
            try:
                new_evidence = live_search(
                    phrases=action.get("phrases") or [],
                    any_of=action.get("any_of") or [],
                    min_year=action.get("min_year"),
                )
            except Exception:  # ponytail: same safety net as corpus_search
                new_evidence = []
            _dedupe_add(evidence, seen_ids, new_evidence)
            continue

        # Malformed even after the repair retry, or a recognized-JSON-but-unknown
        # action name -- either way, this turn produced nothing usable.
        actions_taken.append("invalid")
        notes.append(_INVALID_NOTE)

    return _forced_result(candidate_ctx, evidence, actions_taken, turns)
