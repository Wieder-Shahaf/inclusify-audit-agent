"""Tool: deterministic lexicon scan (the fast first-pass, no LLM cost)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

from .schemas import Chunk, LexiconHit


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


def lexicon_lookup(chunk: Chunk, *, lexicon_path: str | None = None) -> list[LexiconHit]:
    """Return every lexicon match in the chunk's text.

    Case-insensitive, word-boundary matching so substrings inside larger words don't fire.
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
                note=entry.get("note", ""),
            ))
    return hits
