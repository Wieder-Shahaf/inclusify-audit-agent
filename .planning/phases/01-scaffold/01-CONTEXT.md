# Phase 1: Scaffold - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning
**Mode:** Auto-generated (pure infrastructure phase — no grey areas)

<domain>
## Phase Boundary

Deliver a buildable Python 3.11 repo skeleton that lints, tests, and has a valid Docker setup.

**Exit checks (BUILD_PLAN §6, P1):**
1. `ruff check .` exits 0
2. `pytest -q` exits 0 (one import-smoke test — user chose to seed with a real test from phase 1)
3. `python -c "import langgraph, langchain, chromadb"` exits 0
4. `docker compose config` exits 0

</domain>

<decisions>
## Implementation Decisions

### Stack & versions (locked by BUILD_PLAN §5.4 / §6)
- Python 3.11
- Base image: `python:3.11-slim` (confirmed by user)
- Pinned deps in pyproject.toml — version churn is a known risk (BUILD_PLAN §8)
- Branch: `dev` (CLAUDE.md hard rule)

### Phase 1 tests
- One import-smoke test (`tests/test_imports.py`) asserting langgraph, langchain, chromadb, inclusify_agent import cleanly. (User chose: seed Phase 1 with a real test.)

### Project layout (BUILD_PLAN §2 — locked)
- `src/inclusify_agent/` package layout (src-layout)
- `providers/{llm,embeddings,vectorstore}/` subpackages with `base.py` files (interfaces created here, impls in Phase 2)
- `tools/`, `graph/` subpackages exist but empty in Phase 1
- `agent.py`, `report.py`, `ingest.py`, `cli.py`, `api.py` as stubs (only enough to pass import smoke)
- `tests/{unit,contract,e2e}/` directories with `__init__.py`
- `eval/__init__.py` per BUILD_PLAN §5.4

### Docker
- Single multi-stage `Dockerfile` (CPU-only)
- `docker-compose.yml` with two services per BUILD_PLAN §2: `ingest` (one-shot) + `agent`. Chroma is embedded — no separate service.
- `docker compose config` syntax check is the exit gate; image build is NOT required to pass Phase 1.

### Ruff + pytest configuration
- Ruff: standard config in `pyproject.toml` (line-length 100, basic rule set — no aggressive auto-formatting yet)
- pytest: standard config in `pyproject.toml`, test paths point at `tests/`

### Claude's Discretion
- Exact pinned versions (langgraph, langchain, chromadb) — pick the latest stable as of 2026-06 that satisfy the import smoke.
- Specific ruff rule selection — `[E,F,W,I]` is a sensible minimal set.
- README phrasing.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- None yet — Phase 1 is the first code phase.

### Established Patterns
- Memory & CLAUDE.md establish offline-first as the keystone — Phase 1 just creates the empty skeleton; no live behavior yet.
- `.env.example` already exists with the right shape (LLM_PROVIDER=mock, EMBEDDINGS_PROVIDER=hash, VECTOR_STORE=chroma) — Phase 1 does not modify it.

### Integration Points
- Phase 2 will fill in `providers/` impls — Phase 1's base.py files define the seams.
- `data/eric/academic_inclusivity_corpus(in).csv` is already in place; Phase 5 will use it.

</code_context>

<specifics>
## Specific Ideas

None — Phase 1 is pure scaffolding. All decisions trace to BUILD_PLAN §2/§5.4/§6.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
