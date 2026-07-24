"""The v2 detection-stage orchestrator: DocumentAuditor over every window (PRD §4,
BUILD_PLAN R4).

Pure function, one serial pass over the windows — LangGraph `Send` fan-out (parallel
windows) is R5/R6's job; this phase only needs the orchestration to be CORRECT, not
concurrent (BUILD_PLAN R4 exit check + ponytail: don't build fan-out until it's used).
"""
from __future__ import annotations

import re
from typing import Any

from .tools import (
    audit_window,
    build_hints,
    find_quote,
    is_probably_english,
    max_windows,
    parse,
    scan_document,
)
from .tools.schemas import Candidate, Sentence

_WS_RE = re.compile(r"\s+")
# PRD §4 [2] quote-verification acceptance slack: a verified quote's start must fall
# before the window's own content end, plus this much room for trailing overlap noise.
_VERIFY_SLACK = 200


def _normalize_quote(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().lower()


def _find_sentence(sentences: list[Sentence], offset: int) -> Sentence | None:
    """The Sentence containing `offset`, or None (offset lands in a heading/list/gap)."""
    for s in sentences:
        if s.char_start <= offset < s.char_end:
            return s
    return None


def audit_document(
    text: str, *, llm: Any, lexicon_path: str | None = None, window_tokens: int = 1800,
) -> dict[str, Any]:
    """Run the [0] GUARDS + [1] PERCEIVE + [2] DocumentAuditor stages end to end (PRD §4).

    Guards -> parse -> whole-doc lexicon scan -> one Auditor call per window (every
    hint adjudicated, implied bias hunted beyond the hints) -> verbatim-verify every
    candidate quote against the RAW text -> dedupe the overlap zone (two adjacent
    windows can independently re-detect the same physical span) -> group recurring
    framings into one `Candidate` each with every occurrence attached. Never raises
    past the guards. A downstream Investigator stage (R5) consumes `candidates` next.
    """
    if not text or not text.strip():
        raise ValueError("prompt is required and must be non-empty")
    if not is_probably_english(text):
        raise ValueError(
            "Inclusify audits English academic text — the input does not look like English."
        )

    blocks, sentences, windows = parse(text, window_tokens=window_tokens)
    cap = max_windows()
    if len(windows) > cap:
        raise ValueError(
            f"document too large: {len(windows)} windows exceeds the cap of {cap} — "
            "split the document"
        )

    lexicon_hits = scan_document(text, lexicon_path=lexicon_path)

    trace: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    total_hints = 0
    total_raw_candidates = 0
    dropped_unverified = 0

    for window in windows:
        hints = build_hints(lexicon_hits, window)
        result = audit_window(llm, window, hints)
        raw_candidates = result.get("candidates", [])
        hint_verdicts = result.get("hint_verdicts", [])
        total_hints += len(hints)
        total_raw_candidates += len(raw_candidates)

        for cand in raw_candidates:
            found = find_quote(text, cand["quote"], search_start=window.char_start)
            if found is None or found[0] >= window.char_end + _VERIFY_SLACK:
                dropped_unverified += 1
                continue
            start, end = found
            sentence = _find_sentence(sentences, start)
            verified.append({
                "quote": text[start:end],
                "char_start": start,
                "char_end": end,
                "category": cand["category"],
                "reason": cand["reason"],
                "lexicon_backed": cand["lexicon_backed"],
                "window_id": window.id,
                "sentence_id": sentence.id if sentence else None,
            })

        trace.append({
            "node": "audit",
            "window_id": window.id,
            "detail": {
                "hints": len(hints),
                "candidates": len(raw_candidates),
                "hint_verdicts": len(hint_verdicts),
                "verdicts_filled": bool(result.get("verdicts_filled", False)),
            },
        })

    # Overlap-zone dedupe: window i's own tail == window i+1's inherited overlap
    # paragraph, so both can independently re-detect the exact same physical span.
    deduped: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()
    for v in verified:
        span = (v["char_start"], v["char_end"])
        if span in seen_spans:
            continue
        seen_spans.add(span)
        deduped.append(v)

    # Recurrence grouping: the same framing repeated verbatim elsewhere in the doc
    # becomes ONE Candidate with every occurrence attached (PRD §4's recurrence rule;
    # grouping DISTINCT framings into one investigation is R5's job, not this one's).
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for v in deduped:
        key = _normalize_quote(v["quote"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(v)

    candidates: list[Candidate] = []
    for i, key in enumerate(order):
        group = sorted(groups[key], key=lambda v: v["char_start"])
        primary = group[0]
        candidates.append(Candidate(
            id=f"cand{i:04d}",
            quote=primary["quote"],
            char_start=primary["char_start"],
            char_end=primary["char_end"],
            category=primary["category"],
            reason=primary["reason"],
            lexicon_backed=primary["lexicon_backed"],
            window_id=primary["window_id"],
            sentence_id=primary["sentence_id"],
            occurrences=[(v["char_start"], v["char_end"]) for v in group],
        ))

    stats = {
        "windows": len(windows),
        "hints": total_hints,
        "raw_candidates": total_raw_candidates,
        "dropped_unverified": dropped_unverified,
        "candidates": len(candidates),
    }
    trace.append({"node": "audit_summary", "detail": stats})

    return {
        "blocks": blocks,
        "sentences": sentences,
        "windows": windows,
        "lexicon_hits": lexicon_hits,
        "candidates": candidates,
        "trace": trace,
        "stats": stats,
    }
