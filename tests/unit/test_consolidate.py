"""Unit tests for the v2 ReportConsolidator normalization rules (PRD §4 [4],
BUILD_PLAN R6).

Anti-tautology: a scripted stub LLM (not MockLLM) drives `consolidate()` so each
test targets ONE normalization invariant -- unknown ids dropped, a missing id
appended to kept, retracted-wins over kept, parse-failure keeps everything -- never
a MockLLM literal. MockLLM's own scripted behavior (retract-first-low-confidence)
is exercised instead via `tests/e2e/test_v2_full.py`.
"""
from __future__ import annotations

import json

from inclusify_agent.tools import Candidate, Investigation
from inclusify_agent.tools.consolidate import consolidate


class _ScriptedLLM:
    """Replays one response per `.complete()` call; the last response repeats once
    exhausted (a parse-failure test wants "always garbage")."""
    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls.append({"prompt": prompt, "system": system, "kwargs": kwargs})
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


def _json(d: dict) -> str:
    return json.dumps(d)


def _inv(
    id_: str, *, verdict="confirmed", category="gendered", confidence="medium",
    quote="chairman", secondary=None, evidence=None, needs_review=False,
) -> Investigation:
    candidate = Candidate(
        id=id_, quote=quote, char_start=0, char_end=len(quote),
        category=category, reason=f"contains: {quote}", lexicon_backed=True,
        window_id="w0", sentence_id="s0",
    )
    return Investigation(
        candidate=candidate, verdict=verdict, category=category,
        secondary_category=secondary, explanation="expl", rewrite="chairperson",
        confidence=confidence, needs_human_review=needs_review,
        evidence=evidence or [], turns=1, forced=False,
    )


# ---- skip-if-empty ------------------------------------------------------------------------

def test_skip_when_zero_confirmed_makes_no_llm_call() -> None:
    class _BoomLLM:
        def complete(self, *a, **kw):
            raise AssertionError("must not call the LLM when nothing is confirmed")

    result = consolidate(_BoomLLM(), [_inv("c1", verdict="rejected")])

    assert result == {
        "kept": [], "retracted": [], "patterns": [],
        "summary": "No inclusivity issues were confirmed.", "skipped": True,
    }


def test_skip_result_when_investigations_list_is_empty() -> None:
    class _BoomLLM:
        def complete(self, *a, **kw):
            raise AssertionError("must not call the LLM on an empty list")

    assert consolidate(_BoomLLM(), [])["skipped"] is True


# ---- normalization invariants --------------------------------------------------------------

def test_unknown_ids_in_response_are_dropped() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1", "ghost-id"],
        "retracted": [{"id": "c2", "rationale": "duplicate framing"}],
        "patterns": [], "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1"), _inv("c2")])

    assert result["kept"] == ["c1"]
    assert result["retracted"] == [{"id": "c2", "rationale": "duplicate framing"}]


def test_rejected_investigation_ids_are_never_valid_even_if_llm_names_them() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1", "was-rejected"], "retracted": [], "patterns": [], "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1"), _inv("was-rejected", verdict="rejected")])

    assert result["kept"] == ["c1"]


def test_id_missing_from_both_buckets_is_appended_to_kept() -> None:
    """Never silently lose a finding: a confirmed id the model just... doesn't
    mention anywhere still ends up in the report."""
    llm = _ScriptedLLM([_json({
        "kept": ["c1"], "retracted": [], "patterns": [], "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1"), _inv("c2")])

    assert set(result["kept"]) == {"c1", "c2"}
    assert result["retracted"] == []


def test_retracted_wins_when_an_id_appears_in_both_buckets() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1"], "retracted": [{"id": "c1", "rationale": "contradicts doctrine"}],
        "patterns": [], "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1")])

    assert result["kept"] == []
    assert result["retracted"] == [{"id": "c1", "rationale": "contradicts doctrine"}]


def test_parse_failure_after_repair_retry_keeps_everything() -> None:
    llm = _ScriptedLLM(["not json at all", "still not json"])

    result = consolidate(llm, [_inv("c1"), _inv("c2")])

    assert llm.calls, "must have attempted at least one call"
    assert set(result["kept"]) == {"c1", "c2"}
    assert result["retracted"] == []
    assert result["patterns"] == []
    assert result["parse_failed"] is True


def test_one_repair_retry_recovers_from_a_single_bad_reply() -> None:
    llm = _ScriptedLLM(["garbage", _json({
        "kept": ["c1"], "retracted": [], "patterns": [], "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1")])

    assert len(llm.calls) == 2
    assert result["kept"] == ["c1"]
    assert result.get("parse_failed", False) is False


def test_pattern_with_no_valid_ids_is_dropped_others_partially_filtered() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1"], "retracted": [],
        "patterns": [
            {"framing": "all-ghost", "category": "gendered", "finding_ids": ["ghost"]},
            {"framing": "mixed", "category": "gendered", "finding_ids": ["c1", "ghost2"]},
        ],
        "summary": "done",
    })])

    result = consolidate(llm, [_inv("c1")])

    assert len(result["patterns"]) == 1
    assert result["patterns"][0]["framing"] == "mixed"
    assert result["patterns"][0]["finding_ids"] == ["c1"]


# ---- call contract -------------------------------------------------------------------------

def test_llm_is_called_with_task_consolidate_and_compact_findings() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1"], "retracted": [], "patterns": [], "summary": "done",
    })])
    long_quote = "x" * 100

    consolidate(llm, [_inv("c1", category="biased", confidence="high", quote=long_quote)])

    assert llm.calls[0]["kwargs"]["task"] == "consolidate"
    assert llm.calls[0]["system"]  # a non-empty system prompt was passed
    findings = llm.calls[0]["kwargs"]["findings"]
    assert findings[0]["id"] == "c1"
    assert findings[0]["category"] == "biased"
    assert findings[0]["confidence"] == "high"
    assert len(findings[0]["quote"]) <= 80 and findings[0]["quote"].endswith("...")


def test_only_confirmed_investigations_are_sent_to_the_llm() -> None:
    llm = _ScriptedLLM([_json({
        "kept": ["c1"], "retracted": [], "patterns": [], "summary": "done",
    })])

    consolidate(llm, [_inv("c1"), _inv("c2", verdict="rejected")])

    findings = llm.calls[0]["kwargs"]["findings"]
    assert [f["id"] for f in findings] == ["c1"]
