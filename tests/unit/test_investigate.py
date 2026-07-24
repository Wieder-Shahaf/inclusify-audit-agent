"""Unit tests for the v2 EvidenceInvestigator tool loop (PRD §4 [3], BUILD_PLAN R5).

Anti-tautology: a scripted stub LLM (not MockLLM) drives the loop so each test
targets ONE behavior of `investigate()` itself -- turn bookkeeping, the JSON-repair
retry, invalid-action handling, evidence numbering/dedupe, category normalization,
and the stateless re-prompt contract -- never a MockLLM literal.
"""
from __future__ import annotations

import json

from inclusify_agent.tools import Citation, investigate


class _ScriptedLLM:
    """Replays a fixed list of responses, one per `.complete()` call -- a repair
    retry consumes the next entry too. The last entry repeats once the list is
    exhausted, so a turn-cap test can supply a single never-finalizing response."""
    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.prompts.append(prompt)
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


def _action(**fields) -> str:
    return json.dumps(fields)


def _finalize(**overrides) -> str:
    base = {
        "action": "finalize", "verdict": "confirmed", "category": "gendered",
        "secondary_category": None, "explanation": "solid evidence [1]",
        "rewrite": "chairperson", "confidence": "high", "needs_human_review": False,
        "evidence_used": [1],
    }
    base.update(overrides)
    return json.dumps(base)


def _ctx(**overrides) -> dict:
    base = {
        "quote": "chairman", "category": "gendered", "reason": "contains: chairman",
        "sentence_text": "The chairman approved the budget.",
        "paragraph_text": "The chairman approved the budget. It passed unanimously.",
        "alternatives": ["chairperson", "chair"], "occurrences_count": 1,
    }
    base.update(overrides)
    return base


def _no_evidence(query: str) -> list[Citation]:
    return []


# ---- happy path -------------------------------------------------------------------------

def test_happy_path_two_turns_corpus_then_finalize() -> None:
    llm = _ScriptedLLM([_action(action="corpus_search", query="gendered titles"), _finalize()])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence)

    assert result["turns"] == 2
    assert result["actions"] == ["corpus_search", "finalize"]
    assert result["verdict"] == "confirmed"
    assert result["forced"] is False
    assert result["rewrite"] == "chairperson"


# ---- malformed JSON -> one repair retry --------------------------------------------------

def test_malformed_json_gets_one_repair_retry_then_succeeds() -> None:
    llm = _ScriptedLLM([
        "not json at all, sorry about that",
        _action(action="corpus_search", query="x"),
        _finalize(),
    ])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence)

    assert llm.calls == 3, "garbage + one repair + turn 2's finalize = 3 calls"
    assert result["turns"] == 2, "the repair retry must not count as its own turn"
    assert result["actions"] == ["corpus_search", "finalize"]
    assert "Return ONLY the JSON action object." in llm.prompts[1]


# ---- invalid action name -----------------------------------------------------------------

def test_invalid_action_name_counts_turn_and_notes_next_prompt() -> None:
    llm = _ScriptedLLM([_action(action="fly_to_the_moon"), _finalize()])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence)

    assert llm.calls == 2, "a parseable-but-unrecognized action needs no repair call"
    assert result["actions"] == ["invalid", "finalize"]
    assert result["turns"] == 2
    assert "Your last reply was not a valid action." in llm.prompts[1]


# ---- live_search requested but not wired up ----------------------------------------------

def test_live_search_action_when_unavailable_is_treated_invalid() -> None:
    llm = _ScriptedLLM([_action(action="live_search", phrases=["x"]), _finalize()])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence, live_search=None)

    assert result["actions"] == ["invalid", "finalize"]
    assert "live_search is not available" in llm.prompts[1]


# ---- turn-cap exhaustion forces a finalize -----------------------------------------------

def test_turn_cap_exhausted_forces_finalize_never_raises() -> None:
    llm = _ScriptedLLM([_action(action="corpus_search", query="x")])  # never finalizes
    result = investigate(
        llm, _ctx(reason="contains: chairman"), corpus_search=_no_evidence, max_turns=3,
    )

    assert result["forced"] is True
    assert result["turns"] == 3
    assert result["verdict"] == "confirmed"
    assert result["confidence"] == "low"
    assert result["needs_human_review"] is True
    assert result["rewrite"] == ""
    assert "verification incomplete" in result["explanation"]
    assert "contains: chairman" in result["explanation"]


# ---- a flaky tool degrades to "no new evidence", never aborts the loop -------------------

def test_corpus_search_exception_degrades_to_no_new_evidence() -> None:
    def boom(query: str) -> list[Citation]:
        raise RuntimeError("tool exploded")

    llm = _ScriptedLLM([_action(action="corpus_search", query="x"), _finalize()])
    result = investigate(llm, _ctx(), corpus_search=boom)

    assert result["verdict"] == "confirmed"
    assert result["evidence"] == []


# ---- evidence numbering continuity + dedupe by id ----------------------------------------

def test_evidence_numbering_continuity_and_dedupe_by_id() -> None:
    batches = [
        [Citation(id="a", text="first", score=0.9, metadata={"title": "A"}),
         Citation(id="b", text="second", score=0.8, metadata={"title": "B"})],
        [Citation(id="b", text="second", score=0.8, metadata={"title": "B"}),
         Citation(id="c", text="third", score=0.7, metadata={"title": "C"})],
    ]
    calls = iter(batches)

    def corpus_search(query: str) -> list[Citation]:
        return next(calls, [])

    llm = _ScriptedLLM([
        _action(action="corpus_search", query="one"),
        _action(action="corpus_search", query="two"),
        _finalize(evidence_used=[1, 3]),
    ])
    result = investigate(llm, _ctx(), corpus_search=corpus_search)

    assert [e["id"] for e in result["evidence"]] == ["a", "b", "c"], "b must not repeat"
    assert [e["n"] for e in result["evidence"]] == [1, 2, 3]
    assert result["evidence_used"] == [1, 3]


# ---- category normalization ---------------------------------------------------------------

def test_category_and_secondary_category_are_normalized() -> None:
    llm = _ScriptedLLM([_finalize(category="GENDERED", secondary_category="Ableist_Term")])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence)

    assert result["category"] == "gendered"
    # An unmatched secondary normalizes to the safe fallback, same rule as audit_window.
    assert result["secondary_category"] == "potentially-offensive"


def test_secondary_category_none_stays_none() -> None:
    llm = _ScriptedLLM([_finalize(secondary_category=None)])
    result = investigate(llm, _ctx(), corpus_search=_no_evidence)
    assert result["secondary_category"] is None


# ---- stateless re-prompt carries prior evidence ------------------------------------------

def test_stateless_reprompt_contains_prior_evidence_block_on_turn_two() -> None:
    def corpus_search(query: str) -> list[Citation]:
        return [Citation(
            id="eric1", text="UNIQUE_SNIPPET_MARKER", score=0.42,
            metadata={"title": "UNIQUE_TITLE_MARKER", "year": "2020",
                      "url": "https://eric.ed.gov/?id=EJ1"},
        )]

    llm = _ScriptedLLM([_action(action="corpus_search", query="x"), _finalize()])
    investigate(llm, _ctx(), corpus_search=corpus_search)

    assert len(llm.prompts) == 2
    assert "UNIQUE_TITLE_MARKER" not in llm.prompts[0], "turn 1 must not see evidence yet"
    assert "UNIQUE_TITLE_MARKER" in llm.prompts[1]
    assert "[1]" in llm.prompts[1]
