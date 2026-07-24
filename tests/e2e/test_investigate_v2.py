"""E2E tests for the v2 evidence-investigation stage (PRD §4 [3], BUILD_PLAN R5):
`pipeline.investigate_all` / `pipeline.run_v2`, driven end to end by MockLLM's
`investigate` script.

Anti-tautology (BUILD_PLAN §5): asserts structural invariants -- a confirmed verdict
cites its evidence, a rejected one exists, escalation shows up in the trace,
occurrence expansion actually expands, every loop stays within its turn bound,
concurrency stays within its cap -- never MockLLM's literal wording.
"""
from __future__ import annotations

import threading
import time

from inclusify_agent import pipeline
from inclusify_agent.pipeline import audit_document, investigate_all, run_v2
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore
from inclusify_agent.tools import Candidate, Citation

# "chairman" appears twice INSIDE the same short paragraph (one window/one Auditor
# call): the per-window Auditor -- real or mock -- only ever lists a repeated word
# once, and `find_quote` anchors just its first hit, so `audit_document` alone
# under-counts this to ONE occurrence. That's the gap occurrence expansion closes.
_DOC = (
    "The chairman approved the budget for the department today. Later, the "
    "chairman signed the final report before the meeting adjourned.\n\n"
    "Freshmen orientation was organized by student services this term for new "
    "arrivals.\n\n"
    "The master branch is protected from direct pushes in this repository.\n"
)


class _ConcurrencyTrackingLLM:
    """Wraps any LLMProvider; a tiny sleep makes real thread overlap observable, and
    a counting lock records the max number of concurrently in-flight `.complete()`
    calls -- the structural proof that `concurrency=N` actually bounds parallelism."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "tracking")
        self._lock = threading.Lock()
        self._current = 0
        self.max_seen = 0

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        with self._lock:
            self._current += 1
            self.max_seen = max(self.max_seen, self._current)
        try:
            time.sleep(0.01)
            return self.inner.complete(prompt, system=system, **kwargs)
        finally:
            with self._lock:
                self._current -= 1


def _fake_retrieve_citation(store, embedder, *, query, k=3) -> list[Citation]:
    """Deterministic stand-in for the real corpus, dispatching on the model's own
    query text (built as "<category>: <words>" by MockLLM's investigate script) --
    avoids relying on HashEmbeddings' incidental cosine values for score control."""
    q = query.lower()
    if "chairman" in q:
        return [Citation(
            id="eric_chairman", score=0.72,
            text="Occupational titles marked for gender signal exclusion in academic settings.",
            metadata={"title": "Gendered Titles in Academia", "year": "2021",
                      "url": "https://eric.ed.gov/?id=EJ111", "source": "eric"},
        )]
    if "freshmen" in q:
        return [Citation(
            id="eric_freshmen", score=0.10,
            text="Unrelated passage about classroom scheduling.",
            metadata={"title": "Scheduling Norms", "year": "2018",
                      "url": "https://eric.ed.gov/?id=EJ222", "source": "eric"},
        )]
    return []


def _fake_live_search_ladder(
    embedder, *, phrases, any_of=(), min_year=None, k=3,
) -> list[Citation]:
    return [Citation(
        id="eric_live_1", score=0.65,
        text="Live ERIC abstract about inclusive curriculum language.",
        metadata={"title": "Inclusive Curriculum Language", "year": "2022",
                  "url": "https://eric.ed.gov/?id=EJ333", "source": "eric_live", "rung": 1},
    )]


def _wire_live_search(monkeypatch) -> None:
    monkeypatch.setenv("ERIC_LIVE_SEARCH", "1")
    monkeypatch.setattr(pipeline, "retrieve_citation", _fake_retrieve_citation)
    monkeypatch.setattr(pipeline, "live_search_ladder", _fake_live_search_ladder)


def _build_audit_result() -> dict:
    """Real `audit_document()` output on `_DOC`, plus one manually-appended "master"
    candidate: MockLLM's `_audit` script only ever flags its fixed `_flag_words` list
    (chairman/manpower/freshmen/blacklist/his/he) -- "master" is deliberately NOT in
    that list, so the only way to exercise the investigator's own
    reject-as-technical-usage script path is to hand it a candidate directly, exactly
    as a real Auditor call would eventually produce once the lexicon covers
    "master/slave" (PRD §7). Everything downstream of this point is the real
    production code path under test."""
    result = audit_document(_DOC, llm=MockLLM())
    master_sentence = next(s for s in result["sentences"] if "master" in s.text.lower())
    start = _DOC.find("master", master_sentence.char_start)
    manual = Candidate(
        id="cand_master", quote="master", char_start=start, char_end=start + len("master"),
        category="exclusionary", reason="contains: master", lexicon_backed=False,
        window_id=result["windows"][0].id, sentence_id=master_sentence.id,
    )
    result["candidates"] = [*result["candidates"], manual]
    return result


def _by_quote(investigations, quote: str):
    return next(inv for inv in investigations if inv.candidate.quote.lower() == quote)


def test_investigate_all_confirms_rejects_escalates_and_expands_occurrences(monkeypatch) -> None:
    _wire_live_search(monkeypatch)
    audit_result = _build_audit_result()
    store = InMemoryStore(dim=16)
    embedder = HashEmbeddings(dim=16)

    out = investigate_all(_DOC, audit_result, llm=MockLLM(), store=store, embedder=embedder)
    investigations = out["investigations"]

    chairman = _by_quote(investigations, "chairman")
    assert chairman.verdict == "confirmed"
    assert "[1]" in chairman.explanation
    assert chairman.rewrite
    assert len(chairman.candidate.occurrences) == 2, "both raw occurrences must be found"

    master = _by_quote(investigations, "master")
    assert master.verdict == "rejected"

    freshmen = _by_quote(investigations, "freshmen")
    escalation_event = next(
        ev for ev in out["trace"]
        if ev["node"] == "investigate" and ev["candidate_id"] == freshmen.candidate.id
    )
    assert "live_search" in escalation_event["detail"]["actions"], "must have escalated"

    assert all(inv.turns <= 4 for inv in investigations)
    assert out["stats"]["confirmed"] >= 1
    assert out["stats"]["rejected"] >= 1
    summary = next(ev for ev in out["trace"] if ev["node"] == "investigate_summary")
    assert summary["detail"]["confirmed"] == out["stats"]["confirmed"]
    assert summary["detail"]["total_llm_calls"] == sum(inv.turns for inv in investigations)


def test_investigate_all_respects_the_concurrency_cap(monkeypatch) -> None:
    _wire_live_search(monkeypatch)
    audit_result = _build_audit_result()
    store = InMemoryStore(dim=16)
    embedder = HashEmbeddings(dim=16)
    tracking_llm = _ConcurrencyTrackingLLM(MockLLM())

    investigate_all(
        _DOC, audit_result, llm=tracking_llm, store=store, embedder=embedder, concurrency=2,
    )

    assert tracking_llm.max_seen <= 2, "must never run more than the configured cap"

    # Also cover the production default (PRD §8 bound: "≤5 concurrent") explicitly,
    # even though 3 candidates can't stress it as hard as the cap=2 case above did.
    default_tracking_llm = _ConcurrencyTrackingLLM(MockLLM())
    investigate_all(
        _DOC, _build_audit_result(), llm=default_tracking_llm, store=store, embedder=embedder,
    )
    assert default_tracking_llm.max_seen <= 5


def test_run_v2_end_to_end_merges_audit_and_investigate_stages() -> None:
    store = InMemoryStore(dim=16)
    embedder = HashEmbeddings(dim=16)

    out = run_v2("The chairman approved the budget today.", llm=MockLLM(),
                 store=store, embedder=embedder)

    assert out["candidates"], "the audit stage must still run"
    assert out["investigations"], "the investigate stage must run on top of it"
    nodes = {ev["node"] for ev in out["trace"]}
    assert {"audit", "audit_summary", "investigate", "investigate_summary"} <= nodes
    assert "windows" in out["stats"] and "confirmed" in out["stats"], "stats must merge"
