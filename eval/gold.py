"""Gold-set harness scaffold.

BUILD_PLAN §9: real precision/recall numbers are needs-keys (gpt-5-mini + the
Achva gold set). Offline this module ships the *structure* — a tiny synthetic gold
set + scoring functions that work with any audit output.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldItem:
    """A gold-labeled span: the expected (chunk_text, expected_flag)."""
    text: str
    expected_flag: bool
    expected_category: str | None = None


# Synthetic gold set — placeholder for the real Achva set (needs-keys).
GOLD: list[GoldItem] = [
    GoldItem("The chairman approved the budget.", True, "gendered"),
    GoldItem("The committee approved the budget.", False),
    GoldItem("Each student should bring his own laptop.", True, "gendered"),
    GoldItem("All students should bring their laptops.", False),
    GoldItem("The freshmen orientation will be held tomorrow.", True, "gendered"),
    GoldItem("The new-student orientation will be held tomorrow.", False),
    GoldItem("Review the blacklist of plagiarism cases.", True, "exclusionary"),
    GoldItem("Review the blocklist of plagiarism cases.", False),
]


def score(predictions: list[bool], gold: list[GoldItem]) -> dict[str, float]:
    """Return tp/fp/fn/tn + precision/recall/f1 (binary flag-or-not)."""
    if len(predictions) != len(gold):
        raise ValueError(f"len(predictions)={len(predictions)} != len(gold)={len(gold)}")
    tp = sum(1 for p, g in zip(predictions, gold, strict=True) if p and g.expected_flag)
    fp = sum(1 for p, g in zip(predictions, gold, strict=True) if p and not g.expected_flag)
    fn = sum(1 for p, g in zip(predictions, gold, strict=True) if not p and g.expected_flag)
    tn = sum(1 for p, g in zip(predictions, gold, strict=True) if not p and not g.expected_flag)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": precision, "recall": recall, "f1": f1}
