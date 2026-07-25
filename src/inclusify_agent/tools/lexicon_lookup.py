"""Tool: deterministic lexicon scan (the fast first-pass, no LLM cost)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .schemas import Chunk, LexiconHit

# re's alternation gets slow (and risks hitting internal limits) well beyond this many
# alternatives in one compiled pattern, hence chunking scan_document's ~1.5k terms.
_SCAN_CHUNK_SIZE = 500


@lru_cache(maxsize=4)
def load_lexicon(path: str | None = None) -> list[dict]:
    """Load the lexicon JSON.

    Default: use the package-bundled lexicon (works after pip install or in dev).
    Pass an absolute path to override (used by tests with custom fixtures).
    """
    if path:
        with open(Path(path), encoding="utf-8") as f:
            data = json.load(f)
    else:
        resource = files("inclusify_agent.data").joinpath("inclusive_lexicon.json")
        with resource.open("r", encoding="utf-8") as f:
            data = json.load(f)
    return data["entries"]


def _note_with_condition(entry: dict) -> str:
    """Fold the v2 `condition` field into `note`.

    LexiconHit gains no new required field this phase (schemas.py is owned elsewhere
    this wave); `condition`, when present, is prefixed onto `note` as
    ``"condition: <condition>; <note>"`` instead.
    """
    note = entry.get("note", "")
    condition = entry.get("condition", "")
    if not condition:
        return note
    return f"condition: {condition}; {note}" if note else f"condition: {condition}"


def lexicon_lookup(chunk: Chunk, *, lexicon_path: str | None = None) -> list[LexiconHit]:
    """Return every lexicon match in the chunk's text.

    Case-insensitive, word-boundary matching so substrings inside larger words don't fire.
    Unchanged signature/behavior (BUILD_PLAN R2): eval's fixed-pipeline baseline
    (eval/baseline.py) calls this per-chunk.
    """
    entries = load_lexicon(lexicon_path)
    text = chunk.text
    hits: list[LexiconHit] = []
    for entry in entries:
        term: str = entry["term"]
        for m in re.finditer(rf"\b{re.escape(term)}\b", text, flags=re.IGNORECASE):
            hits.append(LexiconHit(
                term=term,
                category=entry["category"],
                alternatives=list(entry["alternatives"]),
                char_start=chunk.char_start + m.start(),
                char_end=chunk.char_start + m.end(),
                note=_note_with_condition(entry),
            ))
    return hits


@lru_cache(maxsize=4)
def _scan_index(lexicon_path: str | None) -> tuple[dict[str, dict], list[re.Pattern]]:
    """Build (and cache) the term->entry map and compiled alternation patterns once per path."""
    entries = load_lexicon(lexicon_path)
    by_term = {e["term"]: e for e in entries}
    # Longest-first so a multiword term (e.g. "sanity check") wins its full span before
    # any single-word alternative in the same chunk could otherwise shadow part of it.
    ordered_terms = sorted(by_term, key=len, reverse=True)
    patterns = []
    for i in range(0, len(ordered_terms), _SCAN_CHUNK_SIZE):
        batch = ordered_terms[i:i + _SCAN_CHUNK_SIZE]
        alternation = "|".join(re.escape(t) for t in batch)
        patterns.append(re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE))
    return by_term, patterns


def scan_document(text: str, *, lexicon_path: str | None = None) -> list[LexiconHit]:
    """Scan an entire raw document once against the full lexicon; absolute char offsets.

    Unlike `lexicon_lookup` (per-chunk, one regex search per term, used by eval's baseline),
    this compiles the whole lexicon into a handful of longest-first alternation patterns
    (batched at `_SCAN_CHUNK_SIZE` terms each) and does one `finditer` pass per pattern,
    so a ~1.5k-term lexicon costs a handful of passes rather than one search per term.
    """
    by_term, patterns = _scan_index(lexicon_path)
    hits: list[LexiconHit] = []
    seen_spans: set[tuple[int, int]] = set()
    for pattern in patterns:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            entry = by_term[m.group().lower()]
            hits.append(LexiconHit(
                term=entry["term"],
                category=entry["category"],
                alternatives=list(entry["alternatives"]),
                char_start=span[0],
                char_end=span[1],
                note=_note_with_condition(entry),
            ))
    hits.sort(key=lambda h: h.char_start)
    return hits
