"""The v2 detection-stage orchestrator: DocumentAuditor over every window (PRD §4,
BUILD_PLAN R4).

Pure function, one serial pass over the windows — LangGraph `Send` fan-out (parallel
windows) is R5/R6's job; this phase only needs the orchestration to be CORRECT, not
concurrent (BUILD_PLAN R4 exit check + ponytail: don't build fan-out until it's used).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .report import render_v2, to_markdown_v2
from .tools import (
    audit_window,
    build_hints,
    eric_live_enabled,
    find_quote,
    investigate,
    is_probably_english,
    live_search_ladder,
    max_windows,
    parse,
    retrieve_citation,
    scan_document,
)
from .tools import consolidate as consolidate_findings
from .tools.schemas import Block, Candidate, Investigation, LexiconHit, Sentence

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
    windows_parse_failed = 0

    for window in windows:
        hints = build_hints(lexicon_hits, window)
        result = audit_window(llm, window, hints)
        raw_candidates = result.get("candidates", [])
        hint_verdicts = result.get("hint_verdicts", [])
        parse_failed = bool(result.get("parse_failed", False))
        total_hints += len(hints)
        total_raw_candidates += len(raw_candidates)
        if parse_failed:
            windows_parse_failed += 1

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
                "parse_failed": parse_failed,
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
        "windows_parse_failed": windows_parse_failed,
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


# ==== v2 evidence investigation (PRD §4 [3] / BUILD_PLAN R5) ==================================
# `audit_document` above is unchanged. Everything below is additive: `investigate_all`
# runs the EvidenceInvestigator tool loop over every candidate it produced, and
# `run_v2` chains the two stages into one call.

_WORD_RE = re.compile(r"\S+")


def _lookup_sentence(sentence_by_id: dict[str, Sentence], candidate: Candidate) -> Sentence | None:
    return sentence_by_id.get(candidate.sentence_id) if candidate.sentence_id else None


def _paragraph_text(blocks: list[Block], sentence: Sentence | None, candidate: Candidate) -> str:
    if sentence is not None:
        return blocks[sentence.block_idx].text
    for b in blocks:
        if b.char_start <= candidate.char_start < b.char_end:
            return b.text
    return candidate.quote


def _alternatives_for(candidate: Candidate, lexicon_hits: list[LexiconHit]) -> list[str]:
    """Lexicon alternatives for hits landing inside any occurrence of this candidate's
    span, deduped in first-seen order."""
    alts: list[str] = []
    seen: set[str] = set()
    for h in lexicon_hits:
        if not any(start <= h.char_start < end for start, end in candidate.occurrences):
            continue
        for a in h.alternatives:
            if a not in seen:
                seen.add(a)
                alts.append(a)
    return alts


def _candidate_ctx(
    candidate: Candidate,
    sentence_by_id: dict[str, Sentence],
    blocks: list[Block],
    lexicon_hits: list[LexiconHit],
) -> dict[str, Any]:
    sentence = _lookup_sentence(sentence_by_id, candidate)
    return {
        "quote": candidate.quote,
        "category": candidate.category,
        "reason": candidate.reason,
        "sentence_text": sentence.text if sentence is not None else candidate.quote,
        "paragraph_text": _paragraph_text(blocks, sentence, candidate),
        "alternatives": _alternatives_for(candidate, lexicon_hits),
        "occurrences_count": len(candidate.occurrences),
    }


def _expand_occurrences(text: str, quote: str) -> list[tuple[int, int]]:
    """Every raw-text occurrence of `quote`, whitespace- and case-normalized (PRD §4
    [3]'s "investigate once, apply everywhere" -- closes an R4 gap): a per-window
    Auditor call names a repeated framing once, and `audit_document`'s own
    `find_quote` anchors only its first hit in that window, so a term repeated within
    ONE window under-counts. Word-boundary-agnostic on purpose (exact phrase match
    after normalization, no `\\b` guards) -- this only ever runs against a candidate's
    own already-confirmed quote, not an arbitrary user pattern.
    """
    words = _WORD_RE.findall(quote)
    if not words:
        return []
    pattern = re.compile(r"\s+".join(re.escape(w) for w in words), re.IGNORECASE)
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def investigate_all(
    text: str,
    audit_result: dict[str, Any],
    *,
    llm: Any,
    store: Any,
    embedder: Any,
    concurrency: int = 5,
) -> dict[str, Any]:
    """Run the [3] EvidenceInvestigator stage over every candidate (PRD §4, BUILD_PLAN R5).

    One investigation per `Candidate` -- `audit_document` already grouped recurring
    framings, so this is "once per distinct framing" by construction. Investigations
    are independent, so they run in parallel over a plain stdlib `ThreadPoolExecutor`;
    wiring this into the LangGraph `Send` fan-out is R6's graph-assembly job, this
    phase only needs the concurrency to actually exist and stay bounded. Confirmed
    verdicts trigger occurrence expansion (`_expand_occurrences`) so a rewrite/verdict
    decided once really does apply everywhere the phrase occurs.
    """
    candidates: list[Candidate] = audit_result.get("candidates", [])
    if not candidates:
        empty_stats = {
            "confirmed": 0, "rejected": 0, "needs_human_review": 0, "total_llm_calls": 0,
            "investigations": 0,
        }
        return {
            "investigations": [],
            "trace": [{"node": "investigate_summary", "detail": empty_stats}],
            "stats": empty_stats,
        }

    sentence_by_id = {s.id: s for s in audit_result.get("sentences", [])}
    blocks: list[Block] = audit_result.get("blocks", [])
    lexicon_hits: list[LexiconHit] = audit_result.get("lexicon_hits", [])

    def corpus_search_fn(query: str) -> list[Any]:
        return retrieve_citation(store, embedder, query=query, k=3)

    live_search_fn = None
    if eric_live_enabled():
        def live_search_fn(*, phrases, any_of=(), min_year=None) -> list[Any]:
            return live_search_ladder(
                embedder, phrases=phrases, any_of=any_of, min_year=min_year, k=3,
            )

    def run_one(candidate: Candidate) -> dict[str, Any]:
        ctx = _candidate_ctx(candidate, sentence_by_id, blocks, lexicon_hits)
        return investigate(llm, ctx, corpus_search=corpus_search_fn, live_search=live_search_fn)

    results_by_id: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_one, c): c.id for c in candidates}
        for future, cid in futures.items():
            results_by_id[cid] = future.result()

    investigations: list[Investigation] = []
    trace: list[dict[str, Any]] = []
    confirmed = rejected = needs_review = total_llm_calls = 0

    for candidate in candidates:
        result = results_by_id[candidate.id]
        if result["verdict"] == "confirmed":
            confirmed += 1
            expanded = _expand_occurrences(text, candidate.quote)
            if expanded:
                candidate.occurrences = expanded
        else:
            rejected += 1
        if result["needs_human_review"]:
            needs_review += 1
        total_llm_calls += result["turns"]

        investigations.append(Investigation(
            candidate=candidate,
            verdict=result["verdict"],
            category=result["category"],
            secondary_category=result["secondary_category"],
            explanation=result["explanation"],
            rewrite=result["rewrite"],
            confidence=result["confidence"],
            needs_human_review=result["needs_human_review"],
            evidence=result["evidence"],
            turns=result["turns"],
            forced=result["forced"],
        ))
        trace.append({
            "node": "investigate",
            "candidate_id": candidate.id,
            "detail": {
                "turns": result["turns"],
                "actions": result["actions"],
                "verdict": result["verdict"],
                "confidence": result["confidence"],
                "evidence_count": len(result["evidence"]),
                "forced": result["forced"],
                "occurrences": len(candidate.occurrences),
            },
        })

    stats = {
        "confirmed": confirmed,
        "rejected": rejected,
        "needs_human_review": needs_review,
        "total_llm_calls": total_llm_calls,
        "investigations": len(investigations),
    }
    trace.append({"node": "investigate_summary", "detail": stats})

    return {"investigations": investigations, "trace": trace, "stats": stats}


def run_v2(
    text: str,
    *,
    llm: Any,
    store: Any,
    embedder: Any,
    lexicon_path: str | None = None,
    window_tokens: int = 1800,
    concurrency: int = 5,
    consolidate: bool = True,
) -> dict[str, Any]:
    """[0]-[4] end to end (PRD §4): guards/parse/DocumentAuditor candidates,
    EvidenceInvestigator verdicts on each, then ReportConsolidator over the
    confirmed ones -- rendered straight into `report`/`markdown` on the returned
    dict, plus a single merged trace and combined stats.

    `consolidate=False` skips [4] entirely (no LLM call, no `report`/`markdown`
    keys) -- callers that only need the raw candidates/investigations (e.g. eval
    harnesses scoring spans directly) don't pay for a call they'd throw away.
    """
    audit_result = audit_document(
        text, llm=llm, lexicon_path=lexicon_path, window_tokens=window_tokens,
    )
    invest_result = investigate_all(
        text, audit_result, llm=llm, store=store, embedder=embedder, concurrency=concurrency,
    )
    result = {
        **audit_result,
        "investigations": invest_result["investigations"],
        "trace": audit_result["trace"] + invest_result["trace"],
        "stats": {**audit_result["stats"], **invest_result["stats"]},
    }
    if not consolidate:
        return result

    consolidation = consolidate_findings(llm, invest_result["investigations"])
    consolidate_trace: list[dict[str, Any]] = [{
        "node": "consolidate",
        "detail": {
            "kept": len(consolidation["kept"]),
            "retracted": len(consolidation["retracted"]),
            "patterns": len(consolidation["patterns"]),
            "skipped": consolidation.get("skipped", False),
        },
    }]
    for r in consolidation["retracted"]:
        consolidate_trace.append({
            "node": "retract", "finding_id": r["id"], "rationale": r["rationale"],
        })

    result["trace"] = result["trace"] + consolidate_trace
    result["consolidation"] = consolidation
    report = render_v2(result, consolidation)
    result["report"] = report
    result["markdown"] = to_markdown_v2(report)
    return result
