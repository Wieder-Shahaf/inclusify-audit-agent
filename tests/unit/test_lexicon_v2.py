"""Unit tests for the v2 lexicon (BUILD_PLAN.md R2): schema, scan_document, build determinism.

Leaves tests/unit/test_tools.py (the v1 lexicon_lookup regression suite) untouched.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from inclusify_agent.tools import Chunk, lexicon_lookup, load_lexicon, scan_document  # noqa: E402
from scripts.build_lexicon import ALLOWED_CATEGORIES, merge_entries  # noqa: E402

FIXTURE_TEXT_PATH = REPO_ROOT / "data" / "fixtures" / "sample.txt"

# The 44 terms bundled in the pre-R2 lexicon; the rebuild must not drop any of them.
LEGACY_44_TERMS = [
    "chairman", "chairmen", "businessman", "businessmen", "salesman", "spokesman", "manpower",
    "mankind", "manmade", "man-hours", "freshmen", "freshman", "policeman", "policemen",
    "fireman", "firemen", "mailman", "blacklist", "whitelist", "master", "slave", "grandfather",
    "sanity check", "dummy", "crazy", "insane", "lame", "tone-deaf", "cripple", "handicapped",
    "gypped", "indian giver", "low man on the totem pole", "spirit animal", "pow-wow", "his",
    "he", "him", "himself", "manning", "guys", "ladies and gentlemen", "third-world", "exotic",
]


# ---- built JSON: schema + invariants -------------------------------------------------

def test_lexicon_has_at_least_1500_entries() -> None:
    assert len(load_lexicon()) >= 1500


def test_every_entry_is_schema_valid() -> None:
    for e in load_lexicon():
        assert e["term"] and isinstance(e["term"], str)
        assert e["category"] in ALLOWED_CATEGORIES, f"{e['term']!r}: bad category {e['category']!r}"
        assert isinstance(e["alternatives"], list)
        if not e["alternatives"]:
            assert e.get("note") or e.get("condition"), (
                f"{e['term']!r} has empty alternatives but no note/condition to explain why"
            )
        assert e.get("source"), f"{e['term']!r} has no source"


def test_no_duplicate_terms() -> None:
    terms = [e["term"] for e in load_lexicon()]
    assert len(terms) == len(set(terms))


def test_all_legacy_terms_survive_the_rebuild() -> None:
    terms = {e["term"] for e in load_lexicon()}
    missing = [t for t in LEGACY_44_TERMS if t not in terms]
    assert not missing, f"legacy terms dropped by the v2 rebuild: {missing}"


# ---- scan_document --------------------------------------------------------------------

def test_scan_document_finds_known_terms_with_correct_offsets() -> None:
    text = FIXTURE_TEXT_PATH.read_text(encoding="utf-8")
    hits = scan_document(text)
    by_term = {h.term: h for h in hits}
    for term in ("chairman", "freshmen", "manpower", "blacklist"):
        assert term in by_term, f"{term!r} not found in fixture scan"
        h = by_term[term]
        matched = text[h.char_start:h.char_end].lower()
        assert matched == term, "offsets must point at the exact match"


def test_scan_document_word_boundary_excludes_substring_matches() -> None:
    # "he" must not fire inside "the" / "committee".
    hits = scan_document("The committee approved the plan.")
    assert not any(h.term == "he" for h in hits)


def test_scan_document_matches_multiword_terms() -> None:
    hits = scan_document("Run a quick sanity check before merging the branch.")
    assert any(h.term == "sanity check" for h in hits)


def test_scan_document_carries_condition_into_note() -> None:
    hits = scan_document("Give the file to his manager directly.")
    his_hits = [h for h in hits if h.term == "his"]
    assert his_hits, "'his' (conditional, gendered) should be flagged"
    assert any("condition:" in h.note for h in his_hits)


def test_scan_document_perf_bounded_75k_chars() -> None:
    unit = "The chairman met the freshmen committee to review the blacklist and manpower plan. "
    text = (unit * (75_000 // len(unit) + 1))[:75_000]
    start = time.perf_counter()
    scan_document(text)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.3, f"scan_document took {elapsed:.3f}s over 75k chars (budget: 300ms)"


# ---- legacy lexicon_lookup path: regression --------------------------------------------

def test_lexicon_lookup_legacy_path_still_returns_hits() -> None:
    chunk = Chunk(id="c0", text="The chairman approved the blacklist.", char_start=0, char_end=37)
    hits = lexicon_lookup(chunk)
    assert any(h.term == "chairman" for h in hits)
    assert any(h.term == "blacklist" for h in hits)


# ---- build determinism: pure merge function, no network -------------------------------

def test_merge_entries_is_deterministic_and_respects_precedence() -> None:
    source_a = [
        {"term": "Chairman", "category": "gendered", "alternatives": ["chair"],
         "note": "", "condition": "", "source": "a"},
        {"term": "master", "category": "exclusionary", "alternatives": [],
         "note": "tech context", "condition": "", "source": "a"},
    ]
    source_b = [
        {"term": "master", "category": "ableist", "alternatives": ["primary"],
         "note": "b-note", "condition": "when technical", "source": "b"},
        {"term": "freshmen", "category": "gendered", "alternatives": ["first-year students"],
         "note": "", "condition": "", "source": "b"},
    ]

    first = merge_entries(source_a, source_b)
    second = merge_entries(source_a, source_b)
    assert first == second, "merge_entries must be a pure, deterministic function"

    by_term = {e["term"]: e for e in first}
    assert set(by_term) == {"chairman", "master", "freshmen"}
    # source_a is listed first, so it wins the category on collision...
    assert by_term["master"]["category"] == "exclusionary"
    # ...but source_a's "master" had no alternatives, so source_b's fill the gap...
    assert by_term["master"]["alternatives"] == ["primary"]
    # ...and notes/conditions from later sources are merged in, never dropped.
    assert "b-note" in by_term["master"]["note"]
    assert by_term["master"]["condition"] == "when technical"
