"""Phase 4 end-to-end: full graph runs on the bundled fixture (BUILD_PLAN §6, P4).

Asserts STRUCTURAL invariants only (§7): trace has the expected event shapes,
findings include retracted/asked items, loop bounded by max_iters. Does NOT
assert on MockLLM string content (anti-tautology rule).
"""
from __future__ import annotations

from pathlib import Path

from inclusify_agent.agent import run_audit
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "sample.txt"


def _seeded_store(emb: HashEmbeddings) -> InMemoryStore:
    """Seed a small grounding corpus so retrieve_citation has something to return."""
    store = InMemoryStore(dim=emb.dim)
    docs = [
        ("g1", "'Chairperson' is preferred over 'chairman' in inclusive academic writing."),
        ("g2", "Use 'workforce' or 'personnel' instead of 'manpower' in academic contexts."),
        ("g3", "'First-year students' is the inclusive replacement for 'freshmen'."),
        ("g4", "'Blocklist' replaces 'blacklist' to avoid racially-coded terminology."),
        ("g5", "Singular they/their is accepted in academic prose for generic reference."),
    ]
    ids = [d[0] for d in docs]
    texts = [d[1] for d in docs]
    metas: list[dict] = [{"src": "fixture-corpus"} for _ in docs]
    store.add(ids=ids, vectors=emb.embed(texts), texts=texts, metadatas=metas)
    return store


def test_audit_runs_end_to_end() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)

    # Schema-shape invariants
    assert "findings" in final
    assert "trace" in final
    assert "step" in final
    assert isinstance(final["findings"], list)
    assert isinstance(final["trace"], list)


def test_audit_produces_at_least_one_finding() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)
    assert len(final["findings"]) >= 1


def test_audit_trace_contains_required_node_events() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)
    trace = final["trace"]
    nodes_seen = {ev.get("node") for ev in trace}
    # The autonomous loop must exercise perceive, route, act, reflect, stop.
    assert {"perceive", "route", "act", "reflect", "stop"} <= nodes_seen


def test_audit_trace_contains_retract_event() -> None:
    """At least one finding must be retracted (the reflect node drops a low-confidence one)."""
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)
    retracted = [f for f in final["findings"] if f.retracted]
    assert len(retracted) >= 1, "no findings retracted; reflect node didn't fire"
    # The reflect event itself appears in the trace.
    reflect_events = [ev for ev in final["trace"] if ev.get("node") == "reflect"]
    assert reflect_events, "no reflect event in trace"
    retracted_ids = reflect_events[0].get("detail", {}).get("retracted_ids")
    assert retracted_ids, "reflect event has no retracted_ids"


def test_audit_loop_stops_within_max_iters() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    max_iters = 30
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=max_iters)
    # step counts every node transition; the bound is on the route node's max_iters check.
    # If the graph escaped its bound, langgraph itself would throw a GraphRecursionError.
    assert final.get("next_action") == "stop"
    # Loose upper bound: step shouldn't be wildly past max_iters * a constant.
    assert final["step"] < max_iters * 5


def test_audit_findings_include_citations_where_grounded() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    emb = HashEmbeddings(dim=64)
    store = _seeded_store(emb)
    final = run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)
    grounded = [f for f in final["findings"] if f.grounded]
    # At least one finding should be grounded (the seeded corpus has matches).
    assert len(grounded) >= 1
    for f in grounded:
        assert f.citation is not None
        assert f.citation.id
