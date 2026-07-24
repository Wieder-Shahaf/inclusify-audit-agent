"""Document-level gold loader + overlap-based span scorer (R3, BUILD_PLAN v0.3 §3 / PRD §10).

`load_doc_gold` reads the JSON produced by `scripts/extract_gold_pdf.py`:
`{"source_pdf", "extracted_at_sha", "fulltext", "spans": [{"char_start", "char_end",
"labels", "page", "text"}], "match_report"}`.

`score` matches predicted spans against gold spans by fractional character overlap
(the fraction is of the GOLD span's length, so a short prediction fully inside a long
gold span still counts) instead of requiring exact offsets — a chunker's span boundaries
rarely land on the same characters as a human's PDF highlight box.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_doc_gold(path: str | Path) -> dict[str, Any]:
    """Load a `doc_gold.json` produced by `scripts/extract_gold_pdf.py`."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _normalize_label(label: str) -> str:
    """"potentially offensive" == "potentially-offensive" == "Potentially-Offensive"."""
    return label.strip().lower().replace(" ", "-")


def _overlap_chars(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _best_gold_match(
    pred: dict[str, Any], gold_spans: list[dict[str, Any]], min_overlap: float,
) -> int | None:
    """Index into `gold_spans` of the highest overlap_fraction (intersection / gold
    span length) that clears `min_overlap`, or None if no gold span clears it."""
    best_idx: int | None = None
    best_frac = 0.0
    for i, gold in enumerate(gold_spans):
        gold_len = gold["char_end"] - gold["char_start"]
        if gold_len <= 0:
            continue
        inter = _overlap_chars(
            pred["char_start"], pred["char_end"], gold["char_start"], gold["char_end"],
        )
        if inter <= 0:
            continue
        frac = inter / gold_len
        if frac >= min_overlap and frac > best_frac:
            best_idx, best_frac = i, frac
    return best_idx


def _is_problem(gold: dict[str, Any]) -> bool:
    """A gold span is a "problem" span if it carries any non-"correct" label."""
    return any(_normalize_label(label) != "correct" for label in gold["labels"])


def _prf1(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def score(
    predicted: list[dict[str, Any]],
    gold_spans: list[dict[str, Any]],
    *,
    min_overlap: float = 0.5,
) -> dict[str, Any]:
    """Score predicted spans (`{"char_start", "char_end", "category"}`) against gold
    spans (`{"char_start", "char_end", "labels": [...]}`) by character overlap.

    - TP: predicted span's best-overlap gold match is a problem span whose labels
      include the predicted category (label-normalized).
    - label_miss: best-overlap match is a problem span, but the category isn't among
      its labels (right span, wrong category) — counted separately from TP/FP.
    - fp_on_correct: best-overlap match is a correct-only span — the precision-killer
      this scorer exists to surface.
    - unmatched_fp: no gold span clears `min_overlap`.
    - FN: a problem gold span matched by no predicted span.

    Pure function — no I/O.
    """
    problem_indices = {i for i, g in enumerate(gold_spans) if _is_problem(g)}

    tp_by_label: dict[str, int] = defaultdict(int)
    fp_by_label: dict[str, int] = defaultdict(int)
    fn_by_label: dict[str, int] = defaultdict(int)
    matched_indices: set[int] = set()
    fp_on_correct = 0
    unmatched_fp = 0
    label_miss = 0

    for pred in predicted:
        category = _normalize_label(pred["category"])
        best_idx = _best_gold_match(pred, gold_spans, min_overlap)
        if best_idx is None:
            unmatched_fp += 1
            fp_by_label[category] += 1
            continue
        if best_idx not in problem_indices:
            fp_on_correct += 1
            fp_by_label[category] += 1
            continue
        gold_labels = {_normalize_label(label) for label in gold_spans[best_idx]["labels"]}
        if category in gold_labels:
            tp_by_label[category] += 1
            matched_indices.add(best_idx)
        else:
            label_miss += 1
            fp_by_label[category] += 1

    for i in problem_indices - matched_indices:
        for label in gold_spans[i]["labels"]:
            norm = _normalize_label(label)
            if norm != "correct":
                fn_by_label[norm] += 1

    labels = sorted(set(tp_by_label) | set(fp_by_label) | set(fn_by_label))
    per_label = {
        label: _prf1(tp_by_label[label], fp_by_label[label], fn_by_label[label])
        for label in labels
    }
    micro = _prf1(sum(tp_by_label.values()), sum(fp_by_label.values()), sum(fn_by_label.values()))

    n_predicted = len(predicted)
    return {
        "per_label": per_label,
        "micro": micro,
        "fp_on_correct": {
            "count": fp_on_correct,
            "rate": fp_on_correct / n_predicted if n_predicted else 0.0,
        },
        "label_miss": label_miss,
        "unmatched_fp": unmatched_fp,
        "n_predicted": n_predicted,
        "n_gold_problem_spans": len(problem_indices),
    }
