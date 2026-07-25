from .audit_window import audit_window, build_hints
from .chunk import chunk, find_quote, parse
from .classify_span import classify_span
from .consolidate import consolidate
from .eric_live_search import eric_live_enabled, eric_live_search, live_search_ladder
from .guards import is_probably_english, max_windows
from .investigate import investigate
from .lexicon_lookup import lexicon_lookup, load_lexicon, scan_document
from .record_finding import record_finding
from .retrieve_citation import retrieve_citation
from .schemas import (
    Block,
    Candidate,
    Chunk,
    Citation,
    Finding,
    Investigation,
    LexiconHit,
    Sentence,
    Window,
)

__all__ = [
    # Retained v1-era tools — also power eval's fixed-pipeline baseline ablation
    "chunk",
    "lexicon_lookup",
    "classify_span",
    "retrieve_citation",
    "record_finding",
    # Live ERIC fallback (env-gated; dormant offline)
    "eric_live_search",
    "eric_live_enabled",
    "live_search_ladder",
    # v2 chunker (PRD §5 / BUILD_PLAN R1) — offset-exact blocks/sentences/windows
    "parse",
    "find_quote",
    "is_probably_english",
    "max_windows",
    # v2 DocumentAuditor (PRD §4 [2] / BUILD_PLAN R4) — hint aggregation + window call
    "build_hints",
    "audit_window",
    # v2 EvidenceInvestigator (PRD §4 [3] / BUILD_PLAN R5) — JSON-action tool loop
    "investigate",
    # v2 ReportConsolidator (PRD §4 [4] / BUILD_PLAN R6) — retract/patterns/severity
    "consolidate",
    # Schemas
    "Chunk",
    "Citation",
    "Finding",
    "LexiconHit",
    "Block",
    "Sentence",
    "Window",
    "Candidate",
    "Investigation",
    # Lexicon loader (re-exported for tests)
    "load_lexicon",
    # Whole-document lexicon scan (BUILD_PLAN R2)
    "scan_document",
]
