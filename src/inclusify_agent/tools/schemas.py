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
