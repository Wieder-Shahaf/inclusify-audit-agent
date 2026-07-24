"""R3 tests: the document-gold overlap scorer (`eval/doc_gold.py`) and the fuzzy
text-matcher in `scripts/extract_gold_pdf.py`.

All fixtures here are tiny SYNTHETIC strings authored for this test — no Achva
content. Real Achva data lives only in the local, gitignored `data/gold/`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from eval.doc_gold import score

REPO_ROOT = Path(__file__).resolve().parents[2]

# `scripts/` isn't an importable package (no __init__, not on pythonpath) and its
# pymupdf import lives inside main()/extract(), so loading the module by file path
# exercises the matcher helpers with zero extra dependencies.
_spec = importlib.util.spec_from_file_location(
    "extract_gold_pdf", REPO_ROOT / "scripts" / "extract_gold_pdf.py",
)
extract_gold_pdf = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(extract_gold_pdf)


def _gold(char_start: int, char_end: int, labels: list[str]) -> dict:
    return {"char_start": char_start, "char_end": char_end, "labels": labels}


def _pred(char_start: int, char_end: int, category: str) -> dict:
    return {"char_start": char_start, "char_end": char_end, "category": category}


# --- eval.doc_gold.score --------------------------------------------------

def test_exact_overlap_is_true_positive() -> None:
    gold = [_gold(0, 20, ["biased"])]
    pred = [_pred(0, 20, "biased")]
    m = score(pred, gold)
    assert m["micro"]["tp"] == 1
    assert m["per_label"]["biased"]["tp"] == 1
    assert m["fp_on_correct"]["count"] == 0
    assert m["label_miss"] == 0
    assert m["unmatched_fp"] == 0


def test_boundary_just_above_min_overlap_passes() -> None:
    # Gold span is 10 chars; a prediction overlapping 6/10 = 60% clears the
    # default 50% bar.
    gold = [_gold(0, 10, ["outdated"])]
    pred = [_pred(0, 6, "outdated")]
    m = score(pred, gold)
    assert m["micro"]["tp"] == 1
    assert m["unmatched_fp"] == 0


def test_boundary_just_below_min_overlap_fails() -> None:
    # 4/10 = 40% overlap does not clear the default 50% bar -> unmatched FP,
    # and the gold span itself goes unmatched -> FN.
    gold = [_gold(0, 10, ["outdated"])]
    pred = [_pred(0, 4, "outdated")]
    m = score(pred, gold)
    assert m["micro"]["tp"] == 0
    assert m["unmatched_fp"] == 1
    assert m["per_label"]["outdated"]["fn"] == 1


def test_multi_label_gold_matches_either_label() -> None:
    gold = [_gold(0, 20, ["outdated", "potentially-offensive"])]
    pred = [_pred(0, 20, "outdated")]
    m = score(pred, gold)
    assert m["micro"]["tp"] == 1
    assert m["per_label"]["outdated"]["tp"] == 1
    assert m["label_miss"] == 0


def test_fp_on_correct_when_predicted_overlaps_a_correct_span() -> None:
    gold = [_gold(0, 20, ["correct"])]
    pred = [_pred(0, 20, "biased")]
    m = score(pred, gold)
    assert m["fp_on_correct"]["count"] == 1
    assert m["fp_on_correct"]["rate"] == 1.0
    assert m["micro"]["tp"] == 0
    # A correct-only gold span is never counted as an FN opportunity.
    assert m["micro"]["fn"] == 0


def test_label_normalization_space_vs_hyphen() -> None:
    gold = [_gold(0, 20, ["potentially offensive"])]
    pred = [_pred(0, 20, "potentially-offensive")]
    m = score(pred, gold)
    assert m["micro"]["tp"] == 1
    assert "potentially-offensive" in m["per_label"]


def test_unmatched_prediction_is_false_positive() -> None:
    gold = [_gold(100, 120, ["biased"])]
    pred = [_pred(0, 20, "biased")]  # nowhere near the gold span
    m = score(pred, gold)
    assert m["unmatched_fp"] == 1
    assert m["micro"]["fp"] == 1
    assert m["micro"]["fn"] == 1  # the gold span itself is never matched


def test_gold_problem_span_with_no_prediction_is_false_negative() -> None:
    gold = [_gold(0, 20, ["biased"]), _gold(50, 70, ["outdated"])]
    pred = [_pred(0, 20, "biased")]
    m = score(pred, gold)
    assert m["per_label"]["outdated"]["fn"] == 1
    assert m["per_label"]["biased"]["fn"] == 0


def test_score_is_pure_and_order_independent() -> None:
    """No I/O; calling twice with the same inputs gives the same result."""
    gold = [_gold(0, 20, ["biased"]), _gold(50, 70, ["correct"])]
    pred = [_pred(0, 20, "biased"), _pred(50, 70, "biased")]
    assert score(pred, gold) == score(pred, gold)


# --- scripts.extract_gold_pdf fuzzy matcher --------------------------------

def test_normalize_collapses_double_spaces() -> None:
    norm, _ = extract_gold_pdf._normalize_for_match("same  gender   text")
    assert norm == "same gender text"


def test_normalize_merges_hyphen_linebreak() -> None:
    # "same-\ngender" (a real line-wrap) whitespace-collapses to "same- gender";
    # the matcher must further merge that into "same-gender".
    norm, _ = extract_gold_pdf._normalize_for_match("same-\ngender orientation")
    assert norm == "same-gender orientation"


def test_find_offset_maps_back_to_original_span_with_real_newline() -> None:
    fulltext = "Intro text. According to the theory, same-\ngender attraction is common."
    start = fulltext.index("same-")
    end = fulltext.index("attraction") + len("attraction")
    norm_full, idx_map = extract_gold_pdf._normalize_for_match(fulltext)

    # Simulates a highlight's quad-extracted text: whitespace-collapsed, hyphen
    # line-break still holding its space ("same- gender", not "same-gender").
    found = extract_gold_pdf._find_offset(
        "same- gender attraction", norm_full, idx_map, start=0, end=len(norm_full),
    )
    assert found is not None
    orig_start, orig_end, _ = found
    assert orig_start == start
    assert orig_end == end
    assert fulltext[orig_start:orig_end] == "same-\ngender attraction"


def test_strip_trailing_clipped_letter() -> None:
    assert extract_gold_pdf._strip_trailing_clipped_letter("gender-atypical f") == "gender-atypical"
    assert extract_gold_pdf._strip_trailing_clipped_letter("no clip here") is None
