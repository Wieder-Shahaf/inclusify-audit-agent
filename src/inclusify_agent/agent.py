"""Top-level run() helper — what the CLI and tests call."""
from __future__ import annotations

from typing import Any

from . import config
from .graph import build_graph
from .providers.embeddings import HashEmbeddings
from .providers.vectorstore import InMemoryStore


def run_audit(
    text: str,
    *,
    llm: Any = None,
    store: Any = None,
    embedder: Any = None,
    max_iters: int | None = None,
) -> dict[str, Any]:
    """Build the graph and run an audit. Returns the final state dict."""
    llm = llm or config.build_llm()
    embedder = embedder or HashEmbeddings(dim=64)
    store = store or InMemoryStore(dim=embedder.dim)

    app = build_graph(llm, store, embedder)
    initial = {
        "document_text": text,
        "findings": [],
        "trace": [],
        "step": 0,
        "max_iters": max_iters or config.get_agent_max_iters(),
        "next_action": "lexicon_lookup",
    }
    # LangGraph's recursion_limit defaults to 25 — our loop is route↔act per chunk
    # plus reflect+stop, so set it to a generous multiple of max_iters.
    recursion_cap = (max_iters or config.get_agent_max_iters()) * 6
    final = app.invoke(initial, {"recursion_limit": recursion_cap})
    return final
