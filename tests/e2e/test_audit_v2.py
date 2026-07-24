"""E2E tests for the v2 detection stage: `pipeline.audit_document` (PRD §4, BUILD_PLAN R4).

Anti-tautology (BUILD_PLAN §5): asserts structural invariants -- verbatim quotes,
overlap dedupe, recurrence grouping, the hint/verdict adjudication contract, bounded
LLM calls, guard rejections -- never MockLLM's literal string content.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from inclusify_agent.pipeline import audit_document
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.server.recording_llm import RecordingLLM

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "sample.txt"

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", s).strip().lower()


def _assert_all_quotes_verbatim(text: str, candidates) -> None:
    for c in candidates:
        exact = text[c.char_start:c.char_end]
        assert exact == c.quote or _norm(exact) == _norm(c.quote), (
            f"candidate {c.id!r} quote {c.quote!r} != raw text {exact!r}"
        )
        for start, end in c.occurrences:
            occ_text = text[start:end]
            assert _norm(occ_text) == _norm(c.quote), (
                f"occurrence ({start},{end}) = {occ_text!r} doesn't match quote {c.quote!r}"
            )


# ---- fixture doc: data/fixtures/sample.txt ---------------------------------------------

def test_audit_document_on_fixture_yields_verified_candidates() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    out = audit_document(text, llm=MockLLM())

    assert out["candidates"], "expected at least one candidate on the fixture doc"
    _assert_all_quotes_verbatim(text, out["candidates"])
    # Known lexicon-backed terms in the fixture (BUILD_PLAN R2's fixture regression set).
    quotes = {c.quote.lower() for c in out["candidates"]}
    assert {"chairman", "freshmen", "blacklist", "manpower"} <= quotes


def test_audit_document_on_fixture_stats_are_internally_consistent() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    out = audit_document(text, llm=MockLLM())
    stats = out["stats"]
    assert stats["windows"] == len(out["windows"])
    assert stats["candidates"] == len(out["candidates"])
    assert stats["raw_candidates"] >= stats["candidates"]
    assert stats["dropped_unverified"] == 0  # MockLLM only ever quotes real matches


def test_audit_document_every_lexicon_hint_gets_adjudicated_on_fixture() -> None:
    """BUILD_PLAN R4 exit check: 'every lexicon hint adjudicated' -- hint count ==
    adjudication (hint_verdicts) count for every window's Auditor call."""
    text = FIXTURE.read_text(encoding="utf-8")
    out = audit_document(text, llm=MockLLM())
    window_events = [ev for ev in out["trace"] if ev["node"] == "audit"]
    assert window_events
    for ev in window_events:
        assert ev["detail"]["hints"] == ev["detail"]["hint_verdicts"]


# ---- synthetic multi-window doc ---------------------------------------------------------
#
# Three oversized filler paragraphs force a 1-block-per-window pack at window_tokens=40
# (verified: each block ~35 est. tokens alone, so two together always exceed 40 and
# force a break) with the standard last-paragraph overlap: w0=[B1], w1=[B1(overlap),B2],
# w2=[B2(overlap),B3]. "manpower" lives only in B2 -- B2 is BOTH w1's own content and
# w2's inherited overlap, so both windows independently re-detect the identical physical
# span (the overlap-dedupe case). "chairman" is planted once in B1 (w0's own content,
# ALSO w1's overlap -- so w0 and w1 collide on the SAME occurrence and dedupe to one)
# and again in B3 (w2's own content only, since B2 -- w2's overlap donor -- never
# mentions it) -- two genuinely distinct offsets that must recurrence-group into one
# Candidate with 2 occurrences.

def _filler(word: str, n_words: int) -> str:
    return " ".join([word] * n_words) + "."


_WINDOW_TOKENS = 40
_B1 = _filler("alpha", 20) + " The chairman signed the first report."
_B2 = _filler("beta", 20) + " The manpower estimate was filed today."
_B3 = _filler("gamma", 20) + " The chairman signed the second report."
_SYNTHETIC_DOC = "\n\n".join([_B1, _B2, _B3])


def _audit_synthetic(llm=None) -> dict:
    return audit_document(_SYNTHETIC_DOC, llm=llm or MockLLM(), window_tokens=_WINDOW_TOKENS)


def test_synthetic_doc_packs_into_exactly_three_windows() -> None:
    # Sanity-check the fixture's own premise before trusting the assertions below.
    out = _audit_synthetic()
    assert len(out["windows"]) == 3


def test_synthetic_doc_quotes_are_all_verbatim() -> None:
    out = _audit_synthetic()
    _assert_all_quotes_verbatim(_SYNTHETIC_DOC, out["candidates"])


def test_synthetic_doc_overlap_span_appears_exactly_once() -> None:
    out = _audit_synthetic()
    manpower = [c for c in out["candidates"] if c.quote.lower() == "manpower"]
    assert len(manpower) == 1, "the overlap-planted span must collapse to one candidate"
    assert len(manpower[0].occurrences) == 1


def test_synthetic_doc_recurring_phrase_groups_into_one_candidate_two_occurrences() -> None:
    out = _audit_synthetic()
    chairman = [c for c in out["candidates"] if c.quote.lower() == "chairman"]
    assert len(chairman) == 1, "the twice-planted phrase must be ONE Candidate"
    occurrences = chairman[0].occurrences
    assert len(occurrences) == 2
    first_offset = _SYNTHETIC_DOC.find("chairman")
    second_offset = _SYNTHETIC_DOC.find("chairman", first_offset + 1)
    assert sorted(o[0] for o in occurrences) == [first_offset, second_offset]


def test_synthetic_doc_adjudication_contract_hints_equal_hint_verdicts() -> None:
    out = _audit_synthetic()
    window_events = [ev for ev in out["trace"] if ev["node"] == "audit"]
    assert len(window_events) == len(out["windows"]) == 3
    for ev in window_events:
        assert ev["detail"]["hints"] == ev["detail"]["hint_verdicts"]


def test_synthetic_doc_exactly_one_audit_call_per_window() -> None:
    # RecordingLLM (server/recording_llm.py) already records one step per `.complete()`
    # call around any provider -- reused here as the counting stub instead of hand-
    # rolling a new wrapper; every call this pipeline makes is task="audit", so the
    # step count IS the audit-call count.
    steps: list[dict] = []
    recording_llm = RecordingLLM(MockLLM(), steps)
    out = _audit_synthetic(llm=recording_llm)
    assert len(steps) == len(out["windows"])


# ---- guards -------------------------------------------------------------------------------

def test_audit_document_rejects_hebrew_dominant_input_with_readable_message() -> None:
    hebrew_text = "שלום עולם זהו טקסט בעברית בלבד ללא אנגלית כלל וכלל היום."
    with pytest.raises(ValueError, match="English"):
        audit_document(hebrew_text, llm=MockLLM())


def test_audit_document_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="prompt is required"):
        audit_document("   ", llm=MockLLM())


def test_audit_document_raises_when_windows_exceed_cap(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_MAX_WINDOWS", "2")
    with pytest.raises(ValueError, match="document too large"):
        audit_document(_SYNTHETIC_DOC, llm=MockLLM(), window_tokens=_WINDOW_TOKENS)
