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

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from .. import config
from ..pipeline import run_v2
from ..providers.vectorstore import InMemoryStore
from ..report import validate_v2
from ..tools import eric_live_enabled, investigate, live_search_ladder, retrieve_citation
from .recording_llm import RecordingLLM
from .seed import seed_store

_PKG_ROOT = Path(__file__).resolve().parents[1]   # src/inclusify_agent
_REPO_ROOT = Path(__file__).resolve().parents[3]   # repo root
_ARCH_PNG = _PKG_ROOT / "static" / "architecture.png"
_EXAMPLES_PATH = _PKG_ROOT / "data" / "agent_info_examples.json"

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
def execute_prompt(prompt: str, *, capture: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run one v2 audit (DocumentAuditor -> EvidenceInvestigator -> ReportConsolidator)
    and shape it into the required {status,error,response,steps}, plus two
    caller-only `tokens_in`/`tokens_out` keys (course req #1c budget ledger) --
    `api_execute` reads them for persistence logging and strips them before the
    HTTP response goes out, so the wire contract stays exactly the four spec fields.

    `capture`, when given a dict, gets the raw `run_v2` result stashed into it under
    `"result"` -- nothing else about this function's behavior or return value changes.
    `/api/ui/execute` uses this to build its report/span payload without re-running
    the pipeline a second time."""
    if not prompt or not prompt.strip():
        return {"status": "error", "error": "prompt is required and must be non-empty",
                "response": None, "steps": [], "tokens_in": None, "tokens_out": None}
    try:
        steps: list[dict[str, Any]] = []
        llm = RecordingLLM(config.build_llm(), steps)
        embedder, store = _shared_rag()
        result = run_v2(prompt, llm=llm, store=store, embedder=embedder)
        if capture is not None:
            capture["result"] = result
        validate_v2(result["report"])

        response = result["markdown"]
        tokens_in = tokens_out = None
        usage_fn = getattr(llm.inner, "usage", None)
        if callable(usage_fn):
            usage = usage_fn()
            if usage.get("in") or usage.get("out"):
                tokens_in, tokens_out = usage["in"], usage["out"]
                response += f"\n\n---\n_Tokens: {tokens_in} in / {tokens_out} out (this audit)_"
        return {"status": "ok", "error": None, "response": response, "steps": steps,
                "tokens_in": tokens_in, "tokens_out": tokens_out}
    except ValueError as e:  # guards (empty / non-English / too-large) -> a clean message
        return {"status": "error", "error": str(e), "response": None, "steps": [],
                "tokens_in": None, "tokens_out": None}
    except Exception as e:  # surface a human-readable error, never 500 the agent
        return {"status": "error", "error": f"{type(e).__name__}: {e}",
                "response": None, "steps": [], "tokens_in": None, "tokens_out": None}


# ----------------------------------------------------------------------------- routes
class ExecuteIn(BaseModel):
    prompt: str


@app.post("/api/execute")
def api_execute(body: ExecuteIn) -> dict[str, Any]:
    result = execute_prompt(body.prompt)
    _persistence.log_run(
        prompt=body.prompt, status=result["status"],
        response=result["response"], steps=result["steps"],
        tokens_in=result["tokens_in"], tokens_out=result["tokens_out"],
    )
    # Wire contract is exactly {status, error, response, steps} (spec §C) -- tokens_*
    # were for the log_run call above only.
    return {k: result[k] for k in ("status", "error", "response", "steps")}


@app.post("/api/ui/execute")
def api_ui_execute(body: ExecuteIn) -> dict[str, Any]:
    """The GUI's structured superset of `/api/execute`: identical status/error/response/
    steps semantics (same `execute_prompt` call, same persistence logging -- this IS a
    real audit, not a preview), plus the validated v2 report and the span/stat sugar
    the frontend needs to render highlights and the fanout view without re-deriving
    them from the markdown."""
    cap: dict[str, Any] = {}
    t0 = time.monotonic()
    result = execute_prompt(body.prompt, capture=cap)
    duration_s = round(time.monotonic() - t0, 1)
    _persistence.log_run(
        prompt=body.prompt, status=result["status"],
        response=result["response"], steps=result["steps"],
        tokens_in=result["tokens_in"], tokens_out=result["tokens_out"],
    )
    base = {k: result[k] for k in ("status", "error", "response", "steps")}
    v2 = cap.get("result")
    if result["status"] != "ok" or v2 is None:
        return {**base, "report": None, "ui": None}

    investigations = v2.get("investigations", [])
    occurrences = {
        inv.candidate.id: [list(occ) for occ in inv.candidate.occurrences]
        for inv in investigations if inv.verdict == "confirmed"
    }
    rejected = [
        {
            "quote": inv.candidate.quote,
            "offsets": [inv.candidate.char_start, inv.candidate.char_end],
            "occurrences": [list(occ) for occ in inv.candidate.occurrences],
            "category": inv.category,
            "explanation": inv.explanation,
            "confidence": inv.confidence,
        }
        for inv in investigations if inv.verdict != "confirmed"
    ]
    return {
        **base,
        "report": v2["report"],
        "ui": {
            "occurrences": occurrences,
            "rejected": rejected,
            "stats": v2.get("stats", {}),
            "duration_s": duration_s,
            "tokens_in": result["tokens_in"],
            "tokens_out": result["tokens_out"],
        },
    }


class WhyIn(BaseModel):
    span: str
    category: str | None = None
    reason: str | None = None


@app.post("/api/why")
def api_why(body: WhyIn) -> dict[str, Any]:
    """On-demand "Why?" — a single-finding EvidenceInvestigator run (PRD §4's module
    map: `/api/why` = one EvidenceInvestigator over a user-supplied span, not a
    whole-document audit). Response contract unchanged from v1's RAG-only version."""
    if not body.span.strip():
        return {"status": "error", "error": "span is required and must be non-empty",
                "explanation": None, "citations": [], "steps": []}
    try:
        steps: list[dict[str, Any]] = []
        llm = RecordingLLM(config.build_llm(), steps)
        embedder, store = _shared_rag()

        def corpus_search_fn(query: str) -> list[Any]:
            return retrieve_citation(store, embedder, query=query, k=3)

        live_search_fn = None
        if eric_live_enabled():
            def live_search_fn(*, phrases, any_of=(), min_year=None) -> list[Any]:
                return live_search_ladder(
                    embedder, phrases=phrases, any_of=any_of, min_year=min_year, k=3,
                )

        candidate_ctx = {
            "quote": body.span,
            "category": body.category or "potentially-offensive",
            "reason": body.reason or "",
            "sentence_text": body.span,
            "paragraph_text": "",
            "alternatives": [],
            "occurrences_count": 1,
        }
        out = investigate(
            llm, candidate_ctx, corpus_search=corpus_search_fn, live_search=live_search_fn,
        )
        result = {
            "status": "ok", "error": None,
            "explanation": out["explanation"],
            "citations": out["evidence"],
            # Backward-compat field (test_api.py pins it): the final turn's user
            # prompt, straight from the RecordingLLM trace rather than threaded
            # through investigate()'s own return contract.
            "augmented_prompt": steps[-1]["prompt"]["User_prompt"] if steps else "",
            "steps": steps,
        }
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
        # Assigned by the course presentation list; env can still override.
        "group_batch_order_number": os.environ.get("GROUP_BATCH_ORDER", "batch1_3"),
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
    """Precomputed on disk by `scripts/gen_examples.py` (PRD §8: a Vercel cold
    start shouldn't re-run the audit pipeline on every request). Falls back to
    computing them on first request when the file isn't there yet."""
    if _EXAMPLES_PATH.exists():
        return json.loads(_EXAMPLES_PATH.read_text(encoding="utf-8"))
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
            "education. It reads human-written English academic text -- papers, "
            "syllabi, slides -- and audits it end to end: a DocumentAuditor reads "
            "the whole document window by window and proposes candidate spans, "
            "including implied bias with no trigger word; parallel "
            "EvidenceInvestigators then research each candidate against a "
            "retrieval corpus (CorpusSearch) and, when local evidence is weak, the "
            "live ERIC API (LiveSearch), confirming or rejecting it with a "
            "grounded explanation and an inclusive rewrite; a final "
            "ReportConsolidator retracts contradicted or duplicate findings, "
            "groups recurring patterns, and orders findings by severity. It "
            "audits text — it never generates course content."
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
def health() -> dict[str, Any]:
    # String getters only -- never build the store/LLM here (spec: cheap + crash-proof).
    return {
        "status": "ok",
        "llm": config.get_llm_provider_name(),
        "model": config.get_llm_model_name(),
        "embeddings": config.get_embeddings_provider_name(),
        "vector_store": config.get_vector_store_name(),
        "persistence": _persistence.name,
        "eric_live": eric_live_enabled(),
    }
