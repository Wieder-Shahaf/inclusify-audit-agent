"""Tool: chunk text into sentence-ish spans with surrounding context."""
from __future__ import annotations

import re

from .schemas import Chunk

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def chunk(text: str, *, context_chars: int = 80) -> list[Chunk]:
    """Split text into sentence-like chunks; carry char offsets + surrounding context.

    Simple regex split — good enough for the offline-first default. Phase 5 / Phase 4
    can swap for a smarter tokenizer if needed.
    """
    if not text or not text.strip():
        return []
    sentences = _SENT_SPLIT.split(text.strip())
    out: list[Chunk] = []
    cursor = 0
    for i, sent in enumerate(sentences):
        if not sent.strip():
            continue
        start = text.find(sent, cursor)
        if start == -1:
            start = cursor
        end = start + len(sent)
        out.append(Chunk(
            id=f"c{i:03d}",
            text=sent,
            context_before=text[max(0, start - context_chars):start],
            context_after=text[end:end + context_chars],
            char_start=start,
            char_end=end,
        ))
        cursor = end
    return out
