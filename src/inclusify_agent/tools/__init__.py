from .ask_user import ask_user
from .audit_window import audit_window, build_hints
from .chunk import chunk, find_quote, parse
from .classify_span import classify_span
from .eric_live_search import eric_live_enabled, eric_live_search
from .explain_why import explain_why
from .guards import is_probably_english, max_windows
from .lexicon_lookup import lexicon_lookup, load_lexicon, scan_document
from .propose_rewrite import propose_rewrite
from .record_finding import record_finding
from .retrieve_citation import retrieve_citation
from .schemas import Block, Candidate, Chunk, Citation, Finding, LexiconHit, Sentence, Window

__all__ = [
    # Tools (7 per BUILD_PLAN)
    "chunk",
    "lexicon_lookup",
    "classify_span",
    "retrieve_citation",
    "propose_rewrite",
    "ask_user",
    "record_finding",
    # On-demand Why?-RAG chain (PRD interactive stage)
    "explain_why",
    # Live ERIC fallback (env-gated; dormant offline)
    "eric_live_search",
    "eric_live_enabled",
    # v2 chunker (PRD §5 / BUILD_PLAN R1) — offset-exact blocks/sentences/windows
    "parse",
    "find_quote",
    "is_probably_english",
    "max_windows",
    # v2 DocumentAuditor (PRD §4 [2] / BUILD_PLAN R4) — hint aggregation + window call
    "build_hints",
    "audit_window",
    # Schemas
    "Chunk",
    "Citation",
    "Finding",
    "LexiconHit",
    "Block",
    "Sentence",
    "Window",
    "Candidate",
    # Lexicon loader (re-exported for tests)
    "load_lexicon",
    # Whole-document lexicon scan (BUILD_PLAN R2)
    "scan_document",
]
