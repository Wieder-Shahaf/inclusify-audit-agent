"""MockLLM must be deterministic.

Critical for BUILD_PLAN §3: e2e tests assert structural invariants on the trace —
the trace stays stable across runs only if MockLLM's outputs are deterministic.
"""
from __future__ import annotations

import json

from inclusify_agent.providers.llm import MockLLM


def test_classify_is_deterministic() -> None:
    llm = MockLLM()
    a = llm.complete("Each student should bring his own laptop", task="classify",
                     span="Each student should bring his own laptop")
    b = llm.complete("Each student should bring his own laptop", task="classify",
                     span="Each student should bring his own laptop")
    assert a == b
    decoded = json.loads(a)
    assert decoded["label"] in {"flag", "skip"}


def test_classify_flags_known_bias() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="classify", span="The chairman approved it."))
    assert out["label"] == "flag"
    assert out["category"] == "gendered"
    assert "chairman" in out["reason"]


def test_classify_skips_clean_text() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="classify", span="The committee approved it."))
    assert out["label"] == "skip"


def test_reflect_drops_low_confidence_finding() -> None:
    llm = MockLLM()
    findings = [
        {"id": "f1", "confidence": "low", "label": "gendered"},
        {"id": "f2", "confidence": "high", "label": "exclusionary"},
    ]
    out = json.loads(llm.complete("", task="reflect", findings=findings))
    assert out["retracted"] == ["f1"]
    assert len(out["kept"]) == 1
    assert out["kept"][0]["id"] == "f2"


def test_rewrite_replaces_known_terms() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="rewrite", span="The chairman approved his report."))
    assert "chairperson" in out["rewrite"]
    assert "their" in out["rewrite"]


def test_route_follows_state_hint() -> None:
    """MockLLM._route picks the next tool based on the last_action in state_hint."""
    llm = MockLLM()
    sequence_pairs = [
        ("lexicon_lookup", "classify_span"),
        ("classify_span", "retrieve_citation"),
        ("retrieve_citation", "propose_rewrite"),
        ("propose_rewrite", "lexicon_lookup"),
        ("ask_user", "lexicon_lookup"),
        ("reflect", "stop"),
    ]
    for last, expected_next in sequence_pairs:
        hint = f"chunk_idx=0/3; last_action={last}; proposed=x; findings=0"
        out = json.loads(llm.complete("", task="route", state_hint=hint))
        actual = out["tool"]
        assert actual == expected_next, f"after {last}, expected {expected_next}, got {actual}"


def test_route_is_deterministic() -> None:
    llm = MockLLM()
    hint = "chunk_idx=1/3; last_action=lexicon_lookup; proposed=classify_span; findings=2"
    a = llm.complete("", task="route", state_hint=hint)
    b = llm.complete("", task="route", state_hint=hint)
    assert a == b


def test_ground_detects_unverified() -> None:
    llm = MockLLM()
    empty = json.loads(llm.complete("", task="ground", citation=""))
    unverified = json.loads(llm.complete("", task="ground", citation="unverified ref"))
    grounded = json.loads(llm.complete("", task="ground", citation="ERIC ED12345"))
    assert empty["status"] == "ungrounded"
    assert unverified["status"] == "ungrounded"
    assert grounded["status"] == "grounded"
