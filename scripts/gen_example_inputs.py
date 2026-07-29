"""Extract the two real-paper example inputs bundled with `GET /api/agent_info`.

The other two `_EXAMPLE_PROMPTS` are one-sentence snippets. A lecturer testing this agent
purely through the HTTP API would otherwise never see it do the thing it claims to do --
audit *academic papers* -- so two real, published, known-problematic papers ship as
example inputs too. Both are sized to pass the `max_windows()` guard, because an example
prompt that the guard rejects is worse than no example at all.

Outputs (committed, so nobody needs to re-run this):
  src/inclusify_agent/data/example_paper_wang_kosinski_2018.txt   6 windows
  src/inclusify_agent/data/example_paper_cohn_2025.txt            9 windows

Sources and why each is cut where it is:

1. Wang & Kosinski (2018), "Deep Neural Networks Are More Accurate Than Humans at
   Detecting Sexual Orientation From Facial Images", J. Personality and Social Psychology
   114(2), 246-257. doi:10.1037/pspa0000098. **(c) American Psychological Association --
   quoted in part, for the purpose of auditing it.**
   This is the repo's document-level gold paper (PRD §11): 88 expert-annotated spans, 32
   of them problems. Cut at char 39844 -- the end of the Study 3 discussion, just before
   the "Study 4: Human Judges" heading -- which is 6 windows and contains 23 of those
   expert-flagged problems across all four labels. Read from the gold extraction rather
   than the PDF so the excerpt's offsets line up with the expert spans in
   data/gold/achva/doc_gold.json (gitignored -- expert gold is never committed).
   The full 75353-char paper is 11 windows and the guard rejects it.

2. Cohn (2025), "Censorship of Essential Debate in Gender Medicine Research",
   Journal of Controversial Ideas 5(2), 3. doi:10.63466/jci05020003.
   **CC BY 4.0** -- open access, so this one ships whole rather than excerpted. Cut at the
   "References" heading (the last 6 of 22 pages are references, which carry no prose to
   audit and would burn 6 of the 10 allowed windows on citation lists).

Usage (the exact invocation that produced the committed files):

    ACHVA="~/inclusify/data/Achva New Data"      # the local, uncommitted Achva drop
    SRC="$ACHVA/מאמרים לבדיקה של המערכת"
    python scripts/gen_example_inputs.py --gold data/gold/achva/doc_gold.json \\
      --cohn-pdf "$SRC/Censorship of Essential Debate in Gender Medicine Research.pdf"

Requires `pdftotext` (poppler) on PATH for the Cohn paper -- same dependency, and the same
subprocess approach, as scripts/extract_gold_pdf.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_DATA = Path(__file__).resolve().parents[1] / "src" / "inclusify_agent" / "data"

# End of the Study 3 discussion in the gold fulltext. Verified: lands on a paragraph
# boundary, yields 6 windows, and keeps 23 expert-flagged problem spans.
_WANG_CUT = 39844


def _wang(gold_path: Path) -> str:
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    text = gold["fulltext"][:_WANG_CUT]
    if not text.rstrip().endswith("locations."):
        raise SystemExit(
            f"gold fulltext changed: char {_WANG_CUT} no longer ends the Study 3 "
            f"discussion (got {text[-40:]!r}). Re-derive the cut before committing."
        )
    return text


def _cohn(pdf_path: Path) -> str:
    raw = subprocess.run(
        ["pdftotext", str(pdf_path), "-"], capture_output=True, text=True, check=True,
    ).stdout
    # Cut at the reference list. rfind, not find: "References" also appears in prose.
    idx = raw.rfind("\nReferences\n")
    if idx == -1:
        raise SystemExit("no 'References' heading found — check the extraction")
    return raw[:idx].rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True, help="data/gold/achva/doc_gold.json")
    ap.add_argument("--cohn-pdf", type=Path, required=True, help="the CC BY paper's PDF")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from inclusify_agent.tools.chunk import parse
    from inclusify_agent.tools.guards import is_probably_english, max_windows

    for name, text in (
        ("example_paper_wang_kosinski_2018.txt", _wang(args.gold.expanduser())),
        ("example_paper_cohn_2025.txt", _cohn(args.cohn_pdf.expanduser())),
    ):
        windows = parse(text)[2]
        # A shipped example the guard would reject is a broken example. Fail loudly here
        # rather than let it reach agent_info.
        if len(windows) > max_windows() or not is_probably_english(text):
            raise SystemExit(
                f"{name}: {len(windows)} windows (cap {max_windows()}), "
                f"english={is_probably_english(text)} — would be rejected by the guards"
            )
        (_DATA / name).write_text(text, encoding="utf-8")
        print(f"wrote {name}: {len(text)} chars, {len(windows)} windows")


if __name__ == "__main__":
    main()
