"""Tool: chunk text into sentence-ish spans with surrounding context."""
from __future__ import annotations

import bisect
import re

from .schemas import Block, Chunk, Sentence, Window

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


# ==== v2 offset-exact parse (PRD §5 / BUILD_PLAN R1) ==========================
# `Chunk`/`chunk()` above are unchanged (v1 graph still uses them). Everything below
# is additive: `parse()` returns the three new units v2 needs — `Block`, `Sentence`,
# `Window` — all offset-exact into the caller's *unmodified* raw string.

# ---- 1. Block parse -----------------------------------------------------------

_BLOCK_SEP_RE = re.compile(r"\n\s*\n")
_HEADING_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)+\.?|\d+\.|[IVXLCDM]+\.)\s+\S")
_LIST_ITEM_RE = re.compile(r"^(?:[-*•]|\d+[.)]|[a-zA-Z][.)])\s+\S")
_HEADING_MAX_WORDS = 12  # ponytail: fixed "short line" cutoff, not configurable — YAGNI


def _split_blocks_raw(raw: str) -> list[tuple[int, int]]:
    """Raw (start, end) spans between blank-line separators (`\\n\\s*\\n`, PRD §5.1)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _BLOCK_SEP_RE.finditer(raw):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(raw):
        spans.append((pos, len(raw)))
    return spans


def _trim_span(raw: str, start: int, end: int) -> tuple[int, int] | None:
    """Trim leading/trailing whitespace off a span; None if it's blank (dropped)."""
    while start < end and raw[start].isspace():
        start += 1
    while end > start and raw[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _looks_all_caps(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def _is_heading(stripped: str) -> bool:
    """Short single line, and (numbered like `2.1`/`III.`, or ALL-CAPS, or no
    terminal punctuation) — PRD §5.1."""
    if not stripped or "\n" in stripped:
        return False
    if len(stripped.split()) > _HEADING_MAX_WORDS:
        return False
    if _HEADING_NUMBERED_RE.match(stripped):
        return True
    if _looks_all_caps(stripped):
        return True
    return stripped[-1] not in ".!?"


def _is_list(lines: list[str]) -> bool:
    """Every non-empty line starts with a bullet/numbered/lettered marker — PRD §5.1."""
    return bool(lines) and all(_LIST_ITEM_RE.match(ln) for ln in lines)


def _classify_block(text: str) -> str:
    stripped = text.strip()
    if _is_heading(stripped):
        return "heading"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if _is_list(lines):
        return "list"
    return "paragraph"


def _parse_blocks(raw: str) -> list[Block]:
    blocks: list[Block] = []
    for raw_start, raw_end in _split_blocks_raw(raw):
        trimmed = _trim_span(raw, raw_start, raw_end)
        if trimmed is None:
            continue
        s, e = trimmed
        text = raw[s:e]
        blocks.append(Block(kind=_classify_block(text), text=text, char_start=s, char_end=e))
    return blocks


# ---- 2. Sentence segmentation --------------------------------------------------

# ~15-entry academic abbreviation list (PRD §5.2), case-insensitive, dot-tolerant.
_ABBREVIATIONS = frozenset({
    "dr", "prof", "et al", "e.g", "i.e", "vs", "cf", "fig", "eq",
    "pp", "no", "vol", "ch", "sec", "approx",
})
_SENT_END_RE = re.compile(r"[.!?…]\s+")
_NEXT_CHAR_OK_RE = re.compile('^[A-Z"\'(0-9]')


def _is_abbreviation(before: str) -> bool:
    """True if `before` (text right up to a candidate sentence-ending mark) ends in a
    known abbreviation. Checks the trailing 1 AND 2 words so two-token entries like
    "et al" match too."""
    words = before.split()
    if not words:
        return False
    last1 = words[-1].strip(".").lower()
    if last1 in _ABBREVIATIONS:
        return True
    if len(words) >= 2:
        last2 = f"{words[-2].strip('.').lower()} {last1}"
        if last2 in _ABBREVIATIONS:
            return True
    return False


def _segment_sentences(raw: str, start: int, end: int) -> list[tuple[int, int]]:
    """Sentence-boundary offsets within raw[start:end], as absolute (start, end) pairs.

    Splits right after `[.!?…]` + whitespace when the preceding token isn't a known
    abbreviation and the next non-space char looks like a sentence start (PRD §5.2).
    The whitespace run between sentences belongs to neither one (same convention as
    block separators). English-only rule.
    """
    text = raw[start:end]
    boundaries: list[tuple[int, int]] = []  # (this sentence's end, next one's start), relative
    for m in _SENT_END_RE.finditer(text):
        punct_end = m.start() + 1
        next_start = m.end()
        if _is_abbreviation(text[:punct_end - 1]):
            continue
        if next_start < len(text) and not _NEXT_CHAR_OK_RE.match(text[next_start]):
            continue
        boundaries.append((punct_end, next_start))
    spans: list[tuple[int, int]] = []
    cursor = 0
    for punct_end, next_start in boundaries:
        spans.append((start + cursor, start + punct_end))
        cursor = next_start
    if cursor < len(text) or not spans:
        spans.append((start + cursor, end))
    return spans


def _parse_sentences(raw: str, blocks: list[Block]) -> list[Sentence]:
    """Sentences within paragraph/list blocks only (PRD §5.2) — headings aren't split."""
    sentences: list[Sentence] = []
    sid = 0
    for idx, b in enumerate(blocks):
        if b.kind not in ("paragraph", "list"):
            continue
        for s_start, s_end in _segment_sentences(raw, b.char_start, b.char_end):
            sentences.append(Sentence(
                id=f"s{sid:04d}", text=raw[s_start:s_end],
                char_start=s_start, char_end=s_end, block_idx=idx,
            ))
            sid += 1
    return sentences


# ---- 3. Window assembly --------------------------------------------------------

# (char_start, char_end, kind, block_idx) — an atomic, must-not-split-further unit.
_Segment = tuple[int, int, str, int]


def _estimate_tokens(text: str) -> float:
    """Rough token estimate (PRD §5.3): word count * 1.3."""
    return len(text.split()) * 1.3


def _atomic_segments(raw: str, blocks: list[Block], window_tokens: int) -> list[_Segment]:
    """Blocks, expanded so no segment alone exceeds `window_tokens` — except a single
    sentence that's already over budget by itself, returned as-is (splitting below
    sentence granularity is out of scope, PRD §5.3)."""
    segments: list[_Segment] = []
    for idx, b in enumerate(blocks):
        if _estimate_tokens(b.text) <= window_tokens:
            segments.append((b.char_start, b.char_end, b.kind, idx))
            continue
        # Oversized single block: fall back to sentence-boundary grouping.
        group_start: int | None = None
        group_end = 0
        group_tokens = 0.0
        for s_start, s_end in _segment_sentences(raw, b.char_start, b.char_end):
            s_tokens = _estimate_tokens(raw[s_start:s_end])
            if group_start is not None and group_tokens + s_tokens > window_tokens:
                segments.append((group_start, group_end, b.kind, idx))
                group_start = None
                group_tokens = 0.0
            if group_start is None:
                group_start = s_start
                group_tokens = 0.0
            group_end = s_end
            group_tokens += s_tokens
        if group_start is not None:
            segments.append((group_start, group_end, b.kind, idx))
    return segments


def _pack_windows(
    raw: str, segments: list[_Segment], window_tokens: int,
) -> list[tuple[list[_Segment], str]]:
    """Greedy-pack segments into (segments, heading_path) windows.

    Prefers breaking before a `heading` segment once the current window is already
    at least half-full (PRD §5.3's "prefer breaking at headings" — a soft
    preference: a heading at the very start of a window never forces an empty one).
    Overlap is added afterwards in `_finalize_windows`, once neighbor windows exist.
    """
    raw_windows: list[tuple[list[_Segment], str]] = []
    cur: list[_Segment] = []
    cur_tokens = 0.0
    heading_so_far = ""
    cur_heading = ""

    def flush() -> None:
        nonlocal cur, cur_tokens
        if cur:
            raw_windows.append((cur, cur_heading))
        cur = []
        cur_tokens = 0.0

    for seg in segments:
        s_start, s_end, kind, _block_idx = seg
        est = _estimate_tokens(raw[s_start:s_end])
        must_break = bool(cur) and (cur_tokens + est > window_tokens)
        prefer_break = bool(cur) and kind == "heading" and cur_tokens >= window_tokens * 0.5
        if must_break or prefer_break:
            flush()
        if not cur:
            cur_heading = heading_so_far
        cur.append(seg)
        cur_tokens += est
        if kind == "heading":
            heading_so_far = raw[s_start:s_end].strip()
            cur_heading = heading_so_far
    flush()
    return raw_windows


def _last_paragraph_segment(segments: list[_Segment]) -> _Segment:
    """The overlap unit handed to the next window: the last `paragraph`-kind segment,
    or — if this window had none (all headings/lists) — its last segment of any kind,
    so overlap stays well-defined (ponytail: documented fallback, not expected on
    realistic prose)."""
    for seg in reversed(segments):
        if seg[2] == "paragraph":
            return seg
    return segments[-1]


def _finalize_windows(raw: str, raw_windows: list[tuple[list[_Segment], str]]) -> list[Window]:
    windows: list[Window] = []
    prev_segments: list[_Segment] | None = None
    for i, (segs, heading_path) in enumerate(raw_windows):
        overlap = _last_paragraph_segment(prev_segments) if prev_segments else None
        all_segs = ([overlap] if overlap else []) + segs
        text = "\n\n".join(raw[s:e] for s, e, _kind, _idx in all_segs)
        char_start = overlap[0] if overlap else segs[0][0]
        overlap_char_end = overlap[1] if overlap else char_start
        windows.append(Window(
            id=f"w{i:03d}",
            text=text,
            char_start=char_start,
            char_end=segs[-1][1],
            heading_path=heading_path,
            block_idxs=[idx for _s, _e, _k, idx in all_segs],
            overlap_char_end=overlap_char_end,
        ))
        prev_segments = segs
    return windows


def parse(
    text: str, *, window_tokens: int = 1800,
) -> tuple[list[Block], list[Sentence], list[Window]]:
    """Offset-exact document parse for the v2 pipeline (PRD §5).

    Two units for two consumers: `windows` for the DocumentAuditor (discourse
    context), `sentences` for anchoring (verbatim quotes, rewrite scope) — sentences
    are never the LLM call unit. `Block`/`Sentence` offsets are always exactly
    `raw[char_start:char_end]`.

    `Window.text` is NOT a single `raw[char_start:char_end]` slice: a window's
    content is the overlap block (if any) plus its own packed blocks, joined with
    "\\n\\n" from each block's own `raw[start:end]` slice — those two groups aren't
    contiguous in the source once the blank-line gaps between blocks are accounted
    for. Use `block_idxs` (or `find_quote`) to map a piece of `text` back to
    absolute raw offsets.
    """
    blocks = _parse_blocks(text)
    sentences = _parse_sentences(text, blocks)
    segments = _atomic_segments(text, blocks, window_tokens)
    raw_windows = _pack_windows(text, segments, window_tokens)
    windows = _finalize_windows(text, raw_windows)
    return blocks, sentences, windows


# ---- 4. Quote verification helper ----------------------------------------------

_WS_RUN_RE = re.compile(r"\s+")


def _normalize_with_map(s: str) -> tuple[str, list[int]]:
    """Collapse whitespace runs to a single space; return (normalized, offset_map)
    where offset_map[i] is the index into `s` that normalized[i] came from."""
    out: list[str] = []
    offset_map: list[int] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            out.append(" ")
            offset_map.append(i)
            while i < n and s[i].isspace():
                i += 1
        else:
            out.append(c)
            offset_map.append(i)
            i += 1
    return "".join(out), offset_map


def find_quote(raw_text: str, quote: str, search_start: int = 0) -> tuple[int, int] | None:
    """Verify a (possibly LLM-mangled) quote against the raw source (PRD §5.4).

    Tries an exact `str.find` first; on failure, falls back to a whitespace-normalized
    match — collapsing all whitespace runs to one space on both sides, via an offset
    map back to raw indices — which recovers quotes split across hard line-wraps.
    NOT handled: hyphenation drift ("same-gender" vs "same- gender") — a hyphen isn't
    whitespace, so normalization can't reconcile it; out of scope per PRD §5.4.
    """
    idx = raw_text.find(quote, search_start)
    if idx != -1:
        return idx, idx + len(quote)
    norm_quote = _WS_RUN_RE.sub(" ", quote).strip()
    if not norm_quote:
        return None
    norm_raw, offset_map = _normalize_with_map(raw_text)
    norm_start = bisect.bisect_left(offset_map, search_start)
    norm_idx = norm_raw.find(norm_quote, norm_start)
    if norm_idx == -1:
        return None
    end_norm = norm_idx + len(norm_quote) - 1
    return offset_map[norm_idx], offset_map[end_norm] + 1
