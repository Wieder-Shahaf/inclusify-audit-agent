"""Classifier eval against the Achva expert review set (held-out rows).

Measures classify_span flag/skip agreement with domain-expert labels. The data is
course/expert material and lives ONLY in data/gold/achva/ (gitignored) — this
script is committed, the data is not. Run with live providers via .env:

    docker run --rm --env-file .env -v "$PWD/src":/app/src:ro \
        -v "$PWD/data":/app/data:ro inclusify-audit-agent-api \
        python -m eval.achva

Measured 2026-07-02 (gpt-5.4-mini, 40 held-out EN rows):
  baseline prompt: acc 60.0%, flag-recall 50.0%, clean-precision 8/8
  expert-exemplar prompt: acc 82.5%, flag-recall 78.1%, clean-precision 8/8
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Rows embedded as few-shot exemplars in classify_span._SYSTEM — excluded from
# the gold measurement so the delta is generalization, not memorization.
EXEMPLAR_IDX = {2, 6, 10, 16, 24, 28, 30, 35, 42, 45, 56, 64, 78}

DEFAULT_DATA = Path("data/gold/achva/review_set.jsonl")


def main(path: Path = DEFAULT_DATA, lang: str = "EN") -> int:
    if not path.exists():
        print(f"achva review set not found at {path} — expert data is local-only "
              "(see .gitignore data/gold/ policy)", file=sys.stderr)
        return 2

    from inclusify_agent import config
    from inclusify_agent.tools import classify_span

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    held = [(i, r) for i, r in enumerate(rows)
            if r["lang"] == lang and i not in EXEMPLAR_IDX]
    llm = config.build_llm()

    tp = fn = tn = fp = 0
    for i, r in held:
        expected = "skip" if r["label"] == "Correct" else "flag"
        out = classify_span(llm, span=r["sentence"])
        got = "skip" if out["label"] == "skip" else "flag"  # 'ask' counts as caution
        print(f"  {i:3d} exp={expected:4s} got={out['label']:4s} [{r['label']}]")
        if expected == "flag":
            tp, fn = (tp + 1, fn) if got == "flag" else (tp, fn + 1)
        else:
            tn, fp = (tn + 1, fp) if got == "skip" else (tn, fp + 1)

    n = len(held)
    print(f"\nn={n}  acc={(tp + tn) / n:.2%}  "
          f"flag-recall={tp / (tp + fn):.2%} ({tp}/{tp + fn})  "
          f"clean-precision={tn}/{tn + fp}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA))
