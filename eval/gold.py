"""Gold-set harness.

Two gold sets available:
- `SYNTHETIC` — 8 hand-crafted items; always available, used by the smoke ablation.
- `ACHVA` — 100 expert-labeled rows (50 EN / 50 HE, 20 per label across the 5 Achva
  categories: Correct, Biased, Potentially Offensive, Factually Incorrect, Outdated).
  Loaded from data/gold/achva_review_set.csv when present.

Achva 5-label → agent 3-label mapping:
- Correct                → skip (no flag expected)
- Biased / Potentially Offensive / Factually Incorrect / Outdated → flag

The agent's existing `flag/ask/skip` schema lets us score this as a binary
(flag-or-not) on a real expert-labeled set without any code-level changes.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoldItem:
    """A gold-labeled span: the expected (chunk_text, expected_flag)."""
    text: str
    expected_flag: bool
    expected_category: str | None = None
    language: str = "EN"  # "EN" or "HE"


# Synthetic gold set — always loadable, used by the smoke ablation.
SYNTHETIC: list[GoldItem] = [
    GoldItem("The chairman approved the budget.", True, "gendered"),
    GoldItem("The committee approved the budget.", False),
    GoldItem("Each student should bring his own laptop.", True, "gendered"),
    GoldItem("All students should bring their laptops.", False),
    GoldItem("The freshmen orientation will be held tomorrow.", True, "gendered"),
    GoldItem("The new-student orientation will be held tomorrow.", False),
    GoldItem("Review the blacklist of plagiarism cases.", True, "exclusionary"),
    GoldItem("Review the blocklist of plagiarism cases.", False),
]

# Default gold set for `eval.run` is SYNTHETIC; switch via --gold achva or
# --gold achva-en when running the eval CLI.
GOLD = SYNTHETIC


# Achva 5-label → 3-label mapping used at load time.
ACHVA_LABEL_TO_FLAG: dict[str, bool] = {
    "Correct": False,
    "Biased": True,
    "Potentially Offensive": True,
    "Factually Incorrect": True,
    "Outdated": True,
}

# Achva raw label → our category string (passed through to the Finding.category check).
ACHVA_LABEL_TO_CATEGORY: dict[str, str] = {
    "Biased": "biased",
    "Potentially Offensive": "potentially-offensive",
    "Factually Incorrect": "factually-incorrect",
    "Outdated": "outdated",
}


def load_achva(
    path: str | Path = "data/gold/achva_review_set.csv",
    *,
    language: str | None = None,
) -> list[GoldItem]:
    """Load the Achva gold review set.

    `language="EN"` or `"HE"` filters to one language; default is both.
    Returns [] (and never raises) if the file is missing — gold data is gitignored.
    """
    p = Path(path)
    if not p.exists():
        return []
    items: list[GoldItem] = []
    with open(p, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lang = row.get("language", "EN")
            if language and lang != language:
                continue
            raw = row.get("expected_label_raw", "")
            expected_flag = ACHVA_LABEL_TO_FLAG.get(raw)
            if expected_flag is None:
                continue
            items.append(GoldItem(
                text=row["sentence"],
                expected_flag=expected_flag,
                expected_category=ACHVA_LABEL_TO_CATEGORY.get(raw),
                language=lang,
            ))
    return items


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
