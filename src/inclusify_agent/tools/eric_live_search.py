"""Tool: live ERIC API search — extra grounding context when the corpus is weak.

The agent elects this tool when local (Pinecone/chroma) retrieval scores below the
grounding floor: instead of giving up and asking the user, it queries the public
ERIC API (api.ies.ed.gov, keyless) for fresh abstracts, scores them with the SAME
embedder as the store (so downstream confidence thresholds stay meaningful), and
merges them into the citation pool.

Offline-first: dormant unless ERIC_LIVE_SEARCH=1 — the tool returns [] without
touching the network. It also never raises; any network failure degrades to []
(the audit then falls back to ask_user exactly as before).
"""
from __future__ import annotations

import html
import json
import os
import urllib.parse
import urllib.request
from typing import Any

from ..providers.vectorstore.inmemory import _cosine
from .schemas import Citation

_API = "https://api.ies.ed.gov/eric/"
_TIMEOUT = 10  # seconds; an audit should never hang on a slow third party


def eric_live_enabled() -> bool:
    return os.environ.get("ERIC_LIVE_SEARCH", "").lower() in ("1", "true", "yes")


def eric_live_search(embedder: Any, *, query: str, k: int = 3) -> list[Citation]:
    """Search ERIC live, cosine-score abstracts against the query, return top-k."""
    if not eric_live_enabled() or not query.strip():
        return []
    params = urllib.parse.urlencode({
        "search": query, "format": "json", "rows": str(k * 2),
        "fields": "id title description publicationdateyear",
    })
    try:
        req = urllib.request.Request(
            _API + "?" + params, headers={"User-Agent": "inclusify-audit-agent/0.1"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            docs = json.loads(resp.read()).get("response", {}).get("docs", [])
    except Exception:  # network/parse failure -> no extra context, never break the audit
        return []

    texts, kept = [], []
    for d in docs:
        desc = d.get("description")
        desc = "; ".join(map(str, desc)) if isinstance(desc, list) else str(desc or "")
        desc = html.unescape(desc)  # ERIC returns HTML-escaped text (&quot; etc.)
        if desc.strip():
            kept.append(d)
            texts.append(desc[:2000])
    if not kept:
        return []

    vecs = embedder.embed([query] + texts)
    qv, dvs = vecs[0], vecs[1:]
    scored = sorted(
        zip(kept, texts, dvs, strict=True),
        key=lambda t: _cosine(qv, t[2]), reverse=True,
    )[:k]
    return [
        Citation(
            id=f"eric_live_{d.get('id', '')}",
            text=text,
            score=_cosine(qv, vec),
            metadata={
                "source": "eric_live",
                "doc_id": str(d.get("id", "")),
                "title": html.unescape(str(d.get("title", "")))[:200],
                "year": str(d.get("publicationdateyear", "") or ""),
                "url": f"https://eric.ed.gov/?id={d.get('id', '')}" if d.get("id") else "",
            },
        )
        for d, text, vec in scored
    ]
