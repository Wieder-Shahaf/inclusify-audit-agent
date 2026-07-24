"""Tool: live ERIC API search — extra grounding context when the corpus is weak.

The agent elects this tool when local (Pinecone/chroma) retrieval scores below the
grounding floor: instead of giving up and asking the user, it queries the public
ERIC API (api.ies.ed.gov, keyless) for fresh abstracts, scores them with the SAME
embedder as the store (so downstream confidence thresholds stay meaningful), and
merges them into the citation pool.

Offline-first: dormant unless ERIC_LIVE_SEARCH=1 — the tool returns [] without
touching the network. It also never raises; any network failure degrades to []
(the audit then falls back to ask_user exactly as before).

`live_search_ladder` (PRD v2.0 §6) adds a compiled-Lucene query ladder on top of the
same fetch/rerank machinery: strict -> relaxed -> broad, stopping at the first rung
with enough grounded evidence. `compile_query` is the pure query-string compiler —
kept separate so it's testable without touching the network.
"""
from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

from ..providers.vectorstore.inmemory import _cosine
from .schemas import Citation

_API = "https://api.ies.ed.gov/eric/"
_TIMEOUT = 10  # seconds; an audit should never hang on a slow third party
_LUCENE_BREAKING = '"():[]'  # ponytail: strip-not-escape; fine for our controlled, short terms


def eric_live_enabled() -> bool:
    return os.environ.get("ERIC_LIVE_SEARCH", "").lower() in ("1", "true", "yes")


# ---- shared fetch / rerank internals -------------------------------------------

def _fetch_eric(query: str, *, rows: int, fields: str) -> list[dict]:
    """GET the ERIC API for a query string. Any failure -> no docs, never raises."""
    params = urllib.parse.urlencode({
        "search": query, "format": "json", "rows": str(rows), "fields": fields,
    })
    try:
        req = urllib.request.Request(
            _API + "?" + params, headers={"User-Agent": "inclusify-audit-agent/0.1"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read()).get("response", {}).get("docs", [])
    except Exception:  # network/parse failure -> caller treats this as an empty rung
        return []


def _docs_with_descriptions(docs: list[dict], *, limit: int = 2000) -> tuple[list[dict], list[str]]:
    """Keep only docs with a non-empty description; unescape HTML, join list-valued fields."""
    kept: list[dict] = []
    texts: list[str] = []
    for d in docs:
        desc = d.get("description")
        desc = "; ".join(map(str, desc)) if isinstance(desc, list) else str(desc or "")
        desc = html.unescape(desc)  # ERIC returns HTML-escaped text (&quot; etc.)
        if desc.strip():
            kept.append(d)
            texts.append(desc[:limit])
    return kept, texts


def _embed_rerank(
    embedder: Any, query_text: str, kept: list[dict], texts: list[str], k: int,
) -> list[tuple[dict, str, float]]:
    """Cosine-rank kept docs' descriptions against query_text with the caller's embedder."""
    vecs = embedder.embed([query_text] + texts)
    qv, dvs = vecs[0], vecs[1:]
    scored = sorted(
        zip(kept, texts, dvs, strict=True), key=lambda t: _cosine(qv, t[2]), reverse=True,
    )[:k]
    return [(d, text, _cosine(qv, vec)) for d, text, vec in scored]


def _to_citation(d: dict, text: str, score: float, *, rung: int | None = None) -> Citation:
    meta = {
        "source": "eric_live",
        "doc_id": str(d.get("id", "")),
        "title": html.unescape(str(d.get("title", "")))[:200],
        "year": str(d.get("publicationdateyear", "") or ""),
        "url": f"https://eric.ed.gov/?id={d.get('id', '')}" if d.get("id") else "",
    }
    if rung is not None:
        meta["rung"] = rung
    return Citation(id=f"eric_live_{d.get('id', '')}", text=text, score=score, metadata=meta)


def eric_live_search(embedder: Any, *, query: str, k: int = 3) -> list[Citation]:
    """Search ERIC live, cosine-score abstracts against the query, return top-k."""
    if not eric_live_enabled() or not query.strip():
        return []
    docs = _fetch_eric(query, rows=k * 2, fields="id title description publicationdateyear")
    kept, texts = _docs_with_descriptions(docs)
    if not kept:
        return []
    ranked = _embed_rerank(embedder, query, kept, texts, k)
    return [_to_citation(d, text, score) for d, text, score in ranked]


# ---- compiled Lucene query ladder (PRD v2.0 §6) --------------------------------

def _clean(term: str) -> str:
    """Strip characters that would break Lucene syntax; the compiler adds quotes itself."""
    return term.translate(str.maketrans("", "", _LUCENE_BREAKING)).strip()


def _plural_variants(terms: Sequence[str]) -> list[str]:
    """Each cleaned term plus a naive plural (term + 's', unless it already ends in 's').

    ponytail: naive singular/plural pair only, no stemmer. ERIC does no stemming either
    (ladder spec: "stereotype" 1,982 hits vs "stereotypes" 18,579) so this is the cheap
    fix for the common case; add a real lemmatizer only if eval shows it still misses.
    """
    out: list[str] = []
    for raw in terms:
        term = _clean(raw)
        if not term or term in out:
            continue
        out.append(term)
        if not term.endswith("s"):
            plural = term + "s"
            if plural not in out:
                out.append(plural)
    return out


def _or_group(terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    return "(" + " OR ".join(terms) + ")"


def compile_query(phrases: list[str], any_of: list[str], min_year: int | None, rung: int) -> str:
    """Compile one rung of the ERIC search ladder into a Lucene query string. Pure function.

    rung 1 (strict) : quoted phrases AND-joined, AND'd any_of OR-group (+ naive plurals),
                       AND peerreviewed:T, AND a publication-year range if min_year is given.
    rung 2 (relaxed): same phrases + any_of group, no peerreviewed/year filter.
    rung 3 (broad)  : every phrase word + any_of term, unquoted and space-joined — implicit
                       OR, the recall net for when strict/relaxed come up dry.
    """
    if rung == 3:
        words = [w for p in phrases for w in _clean(p).split()]
        words += [w for t in any_of if (w := _clean(t))]
        return " ".join(words)

    clauses = [f'"{_clean(p)}"' for p in phrases if _clean(p)]
    any_group = _or_group(_plural_variants(any_of))
    if any_group:
        clauses.append(any_group)
    if rung == 1:
        clauses.append("peerreviewed:T")
        if min_year:
            clauses.append(f"publicationdateyear:[{min_year} TO 2026]")
    return " AND ".join(clauses)


def live_search_ladder(
    embedder: Any,
    *,
    phrases: list[str],
    any_of: Sequence[str] = (),
    min_year: int | None = None,
    k: int = 3,
) -> list[Citation]:
    """Walk the ERIC ladder strict -> relaxed -> broad; stop at the first rung with enough evidence.

    Same offline-first contract as `eric_live_search`: dormant unless ERIC_LIVE_SEARCH=1
    (zero network calls when off), and never raises — a rung that errors or comes up short
    just falls through to the next one, and the whole call degrades to [] if all three do.
    Bounded to at most 3 requests total.
    """
    if not eric_live_enabled() or not (phrases or any_of):
        return []
    any_of = list(any_of)
    query_text = " ".join(list(phrases) + any_of)
    for rung in (1, 2, 3):
        query = compile_query(phrases, any_of, min_year, rung)
        docs = _fetch_eric(
            query, rows=10, fields="id title description publicationdateyear peerreviewed",
        )
        kept, texts = _docs_with_descriptions(docs)
        if len(kept) >= 3:
            ranked = _embed_rerank(embedder, query_text, kept, texts, k)
            return [_to_citation(d, text, score, rung=rung) for d, text, score in ranked]
    return []
