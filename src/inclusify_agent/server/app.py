"""FastAPI app — the assignment-required HTTP API + GUI.

Endpoint names are fixed by the spec and must match exactly:
  GET  /api/team_info          -> student details
  GET  /api/agent_info         -> agent meta + prompt templates/examples
  GET  /api/model_architecture -> image/png of the architecture
  POST /api/execute            -> {status, error, response, steps}
  GET  /                       -> minimal GUI (no auth)

Offline-first: defaults to MockLLM + hash embeddings + a seeded in-memory store,
so every endpoint works with no API keys. Swap providers via env (see config.py).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .. import config
from ..agent import run_audit
from ..providers.vectorstore import InMemoryStore
from ..report import render, to_markdown, validate
from ..tools import explain_why
from .recording_llm import RecordingLLM
from .seed import seed_store

_PKG_ROOT = Path(__file__).resolve().parents[1]   # src/inclusify_agent
_REPO_ROOT = Path(__file__).resolve().parents[3]   # repo root
_ARCH_PNG = _PKG_ROOT / "static" / "architecture.png"

app = FastAPI(title="Inclusify Audit Agent", docs_url="/api/docs", redoc_url=None)

# No auth, GUI must be reachable immediately (spec §3). Permissive CORS so the
# frontend container can call the API cross-origin without preflight friction.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_persistence() -> Any:
    """Run-log sink (Supabase when configured, else no-op). Never crash startup."""
    try:
        return config.build_persistence()
    except Exception as e:  # misconfig / missing client -> degrade to no-op
        import sys

        from ..providers.persistence import NullPersistence
        print(f"[persistence] falling back to null: {type(e).__name__}: {e}", file=sys.stderr)
        return NullPersistence()


_persistence = _build_persistence()


@lru_cache(maxsize=1)
def _shared_rag() -> tuple[Any, Any]:
    """(embedder, vector store) built once from config — the RAG serving the agent.

    Live: the configured store (e.g. Pinecone with the ingested ERIC corpus).
    Offline / keyless / Vercel: falls back to a seeded in-memory demo store so
    every endpoint still works with no keys. Lazy (first request), so importing
    the app never touches the network.
    """
    embedder = config.build_embeddings()
    try:
        store = config.build_vector_store(dim=embedder.dim)
    except Exception as e:  # missing key/client -> keyless demo store
        import sys
        print(f"[store] falling back to seeded in-memory: {type(e).__name__}: {e}",
              file=sys.stderr)
        store = InMemoryStore(dim=embedder.dim)
    if isinstance(store, InMemoryStore):
        seed_store(store, embedder)  # empty per-process store needs the demo seeds
    return embedder, store


# ----------------------------------------------------------------------------- agent
def execute_prompt(prompt: str) -> dict[str, Any]:
    """Run one audit and shape it into the required {status,error,response,steps}."""
    if not prompt or not prompt.strip():
        return {"status": "error", "error": "prompt is required and must be non-empty",
                "response": None, "steps": []}
    try:
        steps: list[dict[str, Any]] = []
        llm = RecordingLLM(config.build_llm(), steps)
        embedder, store = _shared_rag()
        final = run_audit(prompt, llm=llm, embedder=embedder, store=store)
        report = render(final)
        validate(report)
        return {"status": "ok", "error": None,
                "response": to_markdown(report), "steps": steps}
    except Exception as e:  # surface a human-readable error, never 500 the agent
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "response": None, "steps": []}


# ----------------------------------------------------------------------------- routes
class ExecuteIn(BaseModel):
    prompt: str


@app.post("/api/execute")
def api_execute(body: ExecuteIn) -> dict[str, Any]:
    result = execute_prompt(body.prompt)
    _persistence.log_run(
        prompt=body.prompt, status=result["status"],
        response=result["response"], steps=result["steps"],
    )
    return result


class WhyIn(BaseModel):
    span: str
    category: str | None = None
    reason: str | None = None


@app.post("/api/why")
def api_why(body: WhyIn) -> dict[str, Any]:
    """On-demand "Why?" — RAG-grounded explanation for a flagged span (PRD interactive stage)."""
    if not body.span.strip():
        return {"status": "error", "error": "span is required and must be non-empty",
                "explanation": None, "citations": [], "steps": []}
    try:
        steps: list[dict[str, Any]] = []
        llm = RecordingLLM(config.build_llm(), steps)
        embedder, store = _shared_rag()
        out = explain_why(
            llm, store, embedder,
            span=body.span, category=body.category, reason=body.reason,
        )
        result = {"status": "ok", "error": None, "steps": steps, **out}
    except Exception as e:  # same contract as /api/execute: never 500 the agent
        result = {"status": "error", "error": f"{type(e).__name__}: {e}",
                  "explanation": None, "citations": [], "steps": []}
    _persistence.log_run(
        prompt=f"[why] {body.span}", status=result["status"],
        response=result.get("explanation"), steps=result["steps"],
    )
    return result


@app.get("/api/team_info")
def api_team_info() -> dict[str, Any]:
    return {
        # From the presentation list; override via env when assigned.
        "group_batch_order_number": os.environ.get("GROUP_BATCH_ORDER", "TBD_TBD"),
        "team_name": "Inclusify",
        "students": [
            {"name": "Shahaf Wieder", "email": "shahafwieder@campus.technion.ac.il"},
            {"name": "Barak Sharon", "email": "barak.sharon@campus.technion.ac.il"},
        ],
    }


_PROMPT_TEMPLATE = {
    "template": (
        "Paste the course material (a sentence, paragraph, syllabus excerpt, or slide "
        "text) you want audited for non-inclusive language:\n\n<your text here>"
    ),
    "example": "The chairman told the freshmen that manpower was short this semester.",
}

_EXAMPLE_PROMPTS = [
    "The chairman told the freshmen that manpower was short this semester.",
    "The Stonewall Uprising marked a critical juncture in LGBTQ+ rights.",
]


@lru_cache(maxsize=1)
def _examples() -> list[dict[str, Any]]:
    out = []
    for p in _EXAMPLE_PROMPTS:
        r = execute_prompt(p)
        out.append({"prompt": p, "full_response": r["response"], "steps": r["steps"]})
    return out


@app.get("/api/agent_info")
def api_agent_info() -> dict[str, Any]:
    return {
        "description": (
            "Inclusify is an autonomous curriculum-inclusivity auditor for higher "
            "education. It reads human-written course material and flags gendered, "
            "exclusionary, ableist, or culturally-insensitive phrasing, then proposes "
            "inclusive rewrites grounded in a citable corpus. It audits text — it never "
            "generates course content. Pipeline: Chunker -> LexiconScanner -> "
            "SpanClassifier -> CitationRetriever -> RewriteComposer, with a Router "
            "(ReAct control flow) and a Reflector that retracts low-confidence findings."
        ),
        "purpose": (
            "Help educators make papers, syllabi, and slides more inclusive without "
            "losing technical accuracy."
        ),
        "prompt_template": _PROMPT_TEMPLATE,
        "prompt_examples": _examples(),
    }


@app.get("/api/model_architecture")
def api_model_architecture() -> Any:
    if not _ARCH_PNG.exists():
        return JSONResponse(
            {"error": "architecture image not found; run scripts/gen_architecture.py"},
            status_code=500,
        )
    return FileResponse(_ARCH_PNG, media_type="image/png")


# ----------------------------------------------------------------------------- GUI
def _frontend_index() -> str | None:
    for cand in (_REPO_ROOT / "frontend" / "index.html",
                 _PKG_ROOT / "static" / "index.html"):
        if cand.exists():
            return cand.read_text(encoding="utf-8")
    return None


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = _frontend_index()
    if html is None:
        return HTMLResponse("<h1>Inclusify API</h1><p>GUI not bundled. See /api/docs</p>")
    return HTMLResponse(html)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm": config.get_llm_provider_name()}
