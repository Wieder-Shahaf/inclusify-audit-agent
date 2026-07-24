"""Unit tests for the v2 DocumentAuditor per-window tool (PRD §4 [2], BUILD_PLAN R4).

Anti-tautology: audit_window's own normalization/repair/fill-in behavior is asserted
structurally (shapes, counts, never-raises); MockLLM literal strings are only used to
drive the "happy path" through a real provider, not as the thing under test.
"""
from __future__ import annotations

import json

from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.tools import LexiconHit, Window, audit_window, build_hints, scan_document

_KNOWN_CATEGORIES = {
    "gendered", "exclusionary", "ableist", "outdated",
    "factually-incorrect", "potentially-offensive", "biased",
}


def _hit(term: str, start: int, *, category: str = "gendered",
         alternatives: tuple[str, ...] = ("chair",), note: str = "") -> LexiconHit:
    return LexiconHit(term=term, category=category, alternatives=list(alternatives),
                       char_start=start, char_end=start + len(term), note=note)


def _window(*, char_start: int = 0, char_end: int = 10_000, text: str = "w") -> Window:
    return Window(id="w000", text=text, char_start=char_start, char_end=char_end,
                  heading_path="", block_idxs=[0], overlap_char_end=char_start)


# ---- build_hints: grouping / cap / rarest-first / sample-offsets ----------------------

def test_build_hints_groups_by_distinct_term_and_counts_in_window() -> None:
    hits = [_hit("chairman", 0), _hit("chairman", 20), _hit("chairman", 40),
            _hit("freshmen", 60)]
    hints = build_hints(hits, _window())
    by_term = {h["term"]: h for h in hints}
    assert by_term["chairman"]["count"] == 3
    assert by_term["freshmen"]["count"] == 1


def test_build_hints_sample_offsets_capped_at_3_but_count_is_not() -> None:
    hits = [_hit("chairman", i * 20) for i in range(5)]
    hints = build_hints(hits, _window())
    assert hints[0]["count"] == 5
    assert hints[0]["sample_offsets"] == [(0, 8), (20, 28), (40, 48)]


def test_build_hints_rarest_first_by_whole_document_count() -> None:
    # "men" is globally common (5 occurrences across the whole-document `hits` list);
    # "unicorn" is globally rare (1 occurrence). Both have exactly ONE hit inside this
    # window, but rarity ranks by the WHOLE-DOCUMENT count, so "unicorn" -- the more
    # informative, rarer term -- must be listed first (PRD §4 [2]'s "men x64" example).
    hits = ([_hit("men", 0)] + [_hit("men", 1000 + i * 20) for i in range(4)]
            + [_hit("unicorn", 5)])
    hints = build_hints(hits, _window(char_end=10))
    assert [h["term"] for h in hints] == ["unicorn", "men"]


def test_build_hints_caps_at_20_distinct_terms_keeping_rarest() -> None:
    # 25 distinct terms; term{n} has (n+1) whole-document occurrences, so term0 is the
    # single rarest and term24 the most common.
    hits = [_hit(f"term{n}", n * 100) for n in range(25) for _ in range(n + 1)]
    hints = build_hints(hits, _window(char_end=2_600))
    assert len(hints) == 20
    assert {h["term"] for h in hints} == {f"term{n}" for n in range(20)}


def test_build_hints_condition_parsed_from_note() -> None:
    with_condition = _hit(
        "his", 0, note="condition: gendered possessive; use only for a known referent",
    )
    without_condition = _hit("freshmen", 50, note="")
    hints = build_hints([with_condition, without_condition], _window())
    by_term = {h["term"]: h for h in hints}
    assert by_term["his"]["condition"] == "gendered possessive"
    assert by_term["freshmen"]["condition"] == ""


def test_build_hints_condition_only_note_with_no_trailing_text() -> None:
    # `_note_with_condition` emits a bare "condition: X" (no "; note") when the entry
    # itself has no note text -- the parser must not require the "; " separator.
    hit = _hit("guys", 0, note="condition: casual address only")
    hints = build_hints([hit], _window())
    assert hints[0]["condition"] == "casual address only"


def test_build_hints_ignores_hits_outside_window_range() -> None:
    hits = [_hit("chairman", 0), _hit("freshmen", 500)]
    hints = build_hints(hits, _window(char_start=0, char_end=10))
    assert {h["term"] for h in hints} == {"chairman"}


def test_build_hints_alternatives_capped_at_3() -> None:
    hit = _hit("master", 0, alternatives=("primary", "main", "lead", "principal"))
    hints = build_hints([hit], _window())
    assert hints[0]["alternatives"] == ["primary", "main", "lead"]


# ---- audit_window: happy path with MockLLM ---------------------------------------------

def test_audit_window_happy_path_with_mock_llm() -> None:
    text = "The chairman approved the budget for freshmen orientation today."
    window = _window(char_start=0, char_end=len(text), text=text)
    hits = scan_document(text)
    hints = build_hints(hits, window)

    result = audit_window(MockLLM(), window, hints)

    assert len(result["hint_verdicts"]) == len(hints)
    assert result["verdicts_filled"] is False
    quotes = {c["quote"].lower() for c in result["candidates"]}
    assert "chairman" in quotes
    assert "freshmen" in quotes
    for c in result["candidates"]:
        assert c["category"] in _KNOWN_CATEGORIES
        assert c["lexicon_backed"] is True


def test_audit_window_no_hints_no_crash() -> None:
    window = _window(char_start=0, char_end=20, text="A clean sentence here.")
    result = audit_window(MockLLM(), window, hints=[])
    assert result["hint_verdicts"] == []
    assert result["candidates"] == []
    assert result["verdicts_filled"] is False


# ---- audit_window: JSON parse-repair / double-failure paths ----------------------------

class _FlakyLLM:
    """Garbage on the first call, valid JSON on the retry."""
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls += 1
        if self.calls == 1:
            return "this is not json, sorry about that"
        return json.dumps({
            "candidates": [{"quote": "chairman", "category": "gendered",
                             "reason": "gendered title", "lexicon_backed": True}],
            "hint_verdicts": [{"term": "chairman", "verdict": "flag"}],
        })


class _AlwaysBadLLM:
    """Never returns parseable JSON, no matter how many times it's asked."""
    name = "bad"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        self.calls += 1
        return "still not json, even on retry"


def test_audit_window_retries_once_on_parse_failure_then_succeeds() -> None:
    hints = [{"term": "chairman", "category": "gendered", "count": 1,
              "sample_offsets": [(0, 8)], "alternatives": [], "condition": ""}]
    llm = _FlakyLLM()
    result = audit_window(llm, _window(), hints)

    assert llm.calls == 2, "expected exactly one retry after the first parse failure"
    assert "parse_failed" not in result
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["quote"] == "chairman"


def test_audit_window_double_failure_returns_empty_all_clean_never_raises() -> None:
    hints = [{"term": "chairman", "category": "gendered", "count": 1,
              "sample_offsets": [(0, 8)], "alternatives": [], "condition": ""},
             {"term": "freshmen", "category": "gendered", "count": 1,
              "sample_offsets": [(0, 8)], "alternatives": [], "condition": ""}]
    llm = _AlwaysBadLLM()
    result = audit_window(llm, _window(), hints)

    assert llm.calls == 2, "must give up after exactly one retry, not loop forever"
    assert result == {
        "candidates": [],
        "hint_verdicts": [
            {"term": "chairman", "verdict": "clean"},
            {"term": "freshmen", "verdict": "clean"},
        ],
        "parse_failed": True,
    }


# ---- audit_window: category normalization ----------------------------------------------

class _WeirdCategoryLLM:
    name = "weird"

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        return json.dumps({
            "candidates": [
                {"quote": "a", "category": "Factually_Incorrect", "reason": "r",
                 "lexicon_backed": False},
                {"quote": "b", "category": "GENDERED", "reason": "r", "lexicon_backed": False},
                {"quote": "c", "category": "not-a-real-category", "reason": "r",
                 "lexicon_backed": False},
                {"quote": "d", "category": None, "reason": "r", "lexicon_backed": False},
            ],
            "hint_verdicts": [],
        })


def test_audit_window_normalizes_unknown_and_mismatched_categories() -> None:
    result = audit_window(_WeirdCategoryLLM(), _window(), hints=[])
    cats = [c["category"] for c in result["candidates"]]
    assert cats == [
        "factually-incorrect",  # underscore + mixed case -> exact normalized match
        "gendered",             # all-caps -> exact normalized match
        "potentially-offensive",  # no match among the 7 -> safe fallback
        "potentially-offensive",  # missing/None -> safe fallback
    ]


# ---- audit_window: hint_verdicts filling ------------------------------------------------

class _PartialVerdictLLM:
    """Only answers for one of the two hinted terms -- simulates a model 'forgetting'."""
    name = "partial"

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        return json.dumps({
            "candidates": [],
            "hint_verdicts": [{"term": "chairman", "verdict": "flag"}],
        })


def test_audit_window_fills_missing_hint_verdicts_as_clean() -> None:
    hints = [{"term": "chairman", "category": "gendered", "count": 1,
              "sample_offsets": [(0, 8)], "alternatives": [], "condition": ""},
             {"term": "freshmen", "category": "gendered", "count": 1,
              "sample_offsets": [(0, 8)], "alternatives": [], "condition": ""}]
    result = audit_window(_PartialVerdictLLM(), _window(), hints)

    assert len(result["hint_verdicts"]) == 2
    assert {"term": "freshmen", "verdict": "clean"} in result["hint_verdicts"]
    assert {"term": "chairman", "verdict": "flag"} in result["hint_verdicts"]
    assert result["verdicts_filled"] is True
