"""Shared dataclass types for tool inputs/outputs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class Chunk:
    """A span of text plus its surrounding context."""
    id: str
    text: str
    context_before: str = ""
    context_after: str = ""
    char_start: int = 0
    char_end: int = 0


@dataclass
class LexiconHit:
    """A deterministic lexicon match within a chunk."""
    term: str
    category: str
    alternatives: list[str]
    char_start: int
    char_end: int
    note: str = ""


@dataclass
class Citation:
    """A grounding citation retrieved from the corpus."""
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    """A single flagged span with its evidence."""
    id: str
    chunk_id: str
    span: str
    label: str  # "flag" | "ask" | "skip"
    category: str | None
    reason: str
    confidence: Literal["low", "medium", "high"] = "medium"
    rewrite: str | None = None
    citation: Citation | None = None
    grounded: bool = False
    asked: bool = False
    retracted: bool = False


# ---- v2 chunking (PRD §5 / BUILD_PLAN R1) — additive, `Chunk` above stays for v1 -------------

@dataclass
class Block:
    """A blank-line-delimited span of the unmodified raw text (PRD §5.1).

    `text` is always exactly `raw[char_start:char_end]` — offset-exact by construction.
    """
    kind: Literal["heading", "list", "paragraph"]
    text: str
    char_start: int
    char_end: int


@dataclass
class Sentence:
    """An abbreviation-guarded sentence span within a paragraph/list block (PRD §5.2).

    `text` is always exactly `raw[char_start:char_end]`. `block_idx` indexes the
    `blocks` list returned alongside this sentence by `parse()`.
    """
    id: str
    text: str
    char_start: int
    char_end: int
    block_idx: int


@dataclass
class Window:
    """A greedy-packed group of whole blocks sized for one DocumentAuditor call (PRD §5.3).

    `text` is the blocks' raw slices (overlap block, if any, first) joined with "\\n\\n" —
    NOT a single `raw[char_start:char_end]` slice; see `chunk.parse` docstring for why.
    `char_start`/`char_end` span this window's own content: for window 0, `char_start` is
    its first block's start and `overlap_char_end == char_start` (empty overlap). For every
    later window, `char_start` is the start of the copied overlap block (the previous
    window's last paragraph) and `overlap_char_end` is that block's end — so
    `[char_start, overlap_char_end)` is the region shared with the previous window, in
    absolute offsets valid against the same raw text either window came from.
    """
    id: str
    text: str
    char_start: int
    char_end: int
    heading_path: str
    block_idxs: list[int]
    overlap_char_end: int


# ---- v2 auditor candidates (PRD §4 [2] / BUILD_PLAN R4) — additive ----------------------

@dataclass
class Candidate:
    """A verbatim-verified problematic span from the DocumentAuditor (BUILD_PLAN R4).

    `char_start`/`char_end` are the PRIMARY (first, by document order) occurrence's
    absolute offsets. A framing repeated verbatim elsewhere in the doc collapses into
    one `Candidate` whose `occurrences` lists every (start, end) pair, primary first —
    when unset, `occurrences` defaults to that single (char_start, char_end) pair.
    """
    id: str
    quote: str
    char_start: int
    char_end: int
    category: str
    reason: str
    lexicon_backed: bool
    window_id: str
    sentence_id: str | None
    occurrences: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.occurrences:
            self.occurrences = [(self.char_start, self.char_end)]


# ---- v2 investigator verdicts (PRD §4 [3] / BUILD_PLAN R5) — additive -------------------

@dataclass
class Investigation:
    """A verdict + evidence for one `Candidate`, from the EvidenceInvestigator (BUILD_PLAN R5).

    `evidence` is the list of citations shown to the model, in `[n]` order, each a
    plain dict of the `Citation`'s fields (id/text/score/metadata) plus its `n`.
    """
    candidate: Candidate
    verdict: str
    category: str
    secondary_category: str | None
    explanation: str
    rewrite: str
    confidence: str
    needs_human_review: bool
    evidence: list[dict[str, Any]]
    turns: int
    forced: bool
