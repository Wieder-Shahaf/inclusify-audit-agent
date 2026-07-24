"""E2E test for the full v2 chain -- server layer down to the pipeline trace
(PRD §4-§9, BUILD_PLAN R6): DocumentAuditor -> parallel EvidenceInvestigators ->
ReportConsolidator -> report v2.0.

Anti-tautology (BUILD_PLAN §5): asserts structural invariants -- steps[].module
values are a subset of the three real modules, a clean doc makes exactly one
audit call and zero investigator/consolidator calls, a retract event actually
appears in the trace, Hebrew input errors with a readable message -- never
MockLLM's literal wording (module names are the one exception: they're the
assignment-required, spec-locked identifiers themselves, not incidental text).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from inclusify_agent.pipeline import run_v2
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.server import app
from inclusify_agent.server.app import _shared_rag, execute_prompt

client = TestClient(app)

_V2_MODULES = {"DocumentAuditor", "EvidenceInvestigator", "ReportConsolidator"}

# Empirically chosen (three lexicon-backed candidates: chairman/manpower/freshmen):
# against the offline seeded demo store (server/seed.py) + hash embeddings, MockLLM's
# investigate script confirms all three at LOW confidence (weak/no grounding), so the
# consolidator's mock script retracts the first one and keeps the other two -- this
# doc reliably exercises confirm + retract + a non-empty kept findings list in one shot.
_PLANTED_DOC = "The chairman told the freshmen that manpower was short this semester."
_CLEAN_DOC = "The syllabus covers linear algebra."
_HEBREW_DOC = "שלום עולם זהו טקסט בעברית בלבד ללא אנגלית כלל וכלל היום."


def test_planted_doc_execute_prompt_produces_a_full_v2_report() -> None:
    r = execute_prompt(_PLANTED_DOC)

    assert r["status"] == "ok"
    assert r["error"] is None
    md = r["response"]
    assert isinstance(md, str) and md

    # The 5-field-per-finding contract (PRD §1): quote, category, why, evidence
    # (or an explicit ungrounded marker), rewrite.
    assert '"manpower"' in md or '"freshmen"' in md
    assert any(f"[{c}]" in md for c in
               ("gendered", "exclusionary", "ableist", "outdated",
                "factually-incorrect", "potentially-offensive", "biased"))
    assert "Why" in md
    assert "Evidence" in md  # either cited sources or the "(ungrounded)" fallback
    assert "Suggested rewrite" in md

    mods = {s["module"] for s in r["steps"]}
    assert mods, "at least one LLM call must have happened"
    assert mods <= _V2_MODULES


def test_planted_doc_trace_contains_a_retract_event() -> None:
    """`execute_prompt` doesn't expose the internal node-trace (only steps[] is
    part of the HTTP contract) -- replay the SAME doc through `run_v2` directly,
    reusing the identical shared (embedder, store) `execute_prompt` just seeded,
    to inspect the retract event BUILD_PLAN §5 requires."""
    execute_prompt(_PLANTED_DOC)  # ensure _shared_rag() has been built+seeded
    embedder, store = _shared_rag()

    result = run_v2(_PLANTED_DOC, llm=MockLLM(), store=store, embedder=embedder)

    retract_events = [ev for ev in result["trace"] if ev.get("node") == "retract"]
    assert len(retract_events) >= 1
    assert retract_events[0]["rationale"]
    consolidate_summary = next(ev for ev in result["trace"] if ev["node"] == "consolidate")
    assert consolidate_summary["detail"]["retracted"] >= 1
    assert consolidate_summary["detail"]["skipped"] is False


def test_clean_doc_makes_exactly_one_audit_call_and_reports_no_issues() -> None:
    r = execute_prompt(_CLEAN_DOC)

    assert r["status"] == "ok"
    assert [s["module"] for s in r["steps"]] == ["DocumentAuditor"]
    assert "No inclusivity issues were confirmed" in r["response"]


def test_hebrew_input_returns_a_human_readable_error() -> None:
    r = execute_prompt(_HEBREW_DOC)

    assert r["status"] == "error"
    assert "English" in r["error"]
    assert r["response"] is None
    assert r["steps"] == []


def test_why_endpoint_runs_a_single_finding_evidence_investigator() -> None:
    r = client.post("/api/why", json={
        "span": "The chairman approved the budget.", "category": "gendered",
    })

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert isinstance(body["citations"], list)
    assert any(s["module"] == "EvidenceInvestigator" for s in body["steps"])
