# Roadmap: Inclusify Audit Agent

## Overview

Build the standalone autonomous Inclusify Audit Agent (LangGraph ReAct + Reflection + Agentic-RAG) fully
offline behind mock/local providers — phase by phase, each exiting on a command that returns 0 (the offline
Definition of Done). Full design: `docs/PRD.md`; process, guardrails, and per-phase detail: `docs/BUILD_PLAN.md`.

## Phases

- [x] **Phase 1: Scaffold** - repo skeleton, pinned deps, ruff/pytest, Docker, import smoke
- [x] **Phase 2: Providers** - LLM/embeddings/vectorstore interfaces + mock/local impls + contract tests
- [x] **Phase 3: Tools** - the 7 agent tools + unit tests
- [x] **Phase 4: Graph** - LangGraph ReAct + Reflection + Agentic-RAG routing + trace + offline e2e
- [x] **Phase 5: Ingest** - ERIC → Chroma (hash embedder gate, no network)
- [x] **Phase 6: Report + Entrypoints** - output schema + renderer + CLI/API
- [x] **Phase 7: Eval + Ablation** - gold harness + agent-vs-pipeline control-flow divergence
- [x] **Phase 8: Package** - end-to-end Docker offline demo, needs-keys checklist, ponytail audit + debt

## Phase Details

### Phase 1: Scaffold
**Goal**: A buildable Python 3.11 repo skeleton that lints, tests, and has a valid Docker setup.
**Depends on**: Nothing (first phase)
**Requirements**: offline-first, standalone, Docker
**Success Criteria** (what must be TRUE):
  1. `ruff check .` exits 0
  2. `pytest -q` exits 0 (0 tests is acceptable)
  3. `python -c "import langgraph, langchain, chromadb"` exits 0
  4. `docker compose config` exits 0
**Plans**: 2 plans

Plans:
- [ ] 01-01: pyproject (pinned deps), ruff/pytest config, package layout
- [ ] 01-02: Dockerfile (python:3.11-slim) + docker-compose (ingest + agent) + README + import-smoke test

### Phase 2: Providers
**Goal**: Offline-first provider abstraction so every LLM/embeddings/vector call runs with no API key.
**Depends on**: Phase 1
**Requirements**: offline-first; provider interfaces (YAGNI-exempt keystone)
**Success Criteria** (what must be TRUE):
  1. `pytest tests/contract -q` exits 0 — every LLM/embeddings/vectorstore impl satisfies its interface
  2. MockLLM is deterministic and drives classify, route, AND reflect call-sites
  3. `hash` embedder + local Chroma work with no network and no key
**Plans**: 2 plans

Plans:
- [ ] 02-01: LLMProvider (MockLLM + OpenAICompatLLM + AzureOpenAILLM stub) + determinism test
- [ ] 02-02: EmbeddingsProvider (hash/local_st/openai_compat/azure) + VectorStore (chroma/inmemory/qdrant) + contract suite

### Phase 3: Tools
**Goal**: The 7 agent tools, each thin and unit-tested.
**Depends on**: Phase 2
**Success Criteria** (what must be TRUE):
  1. `pytest tests/unit -q` exits 0
  2. chunk, lexicon_lookup, classify_span, retrieve_citation, propose_rewrite, ask_user, record_finding each have a unit test
  3. lexicon_lookup loads the bundled retext-equality + Tiny Heap data
**Plans**: 2 plans

Plans:
- [ ] 03-01: chunk, lexicon_lookup, classify_span, propose_rewrite + tests
- [ ] 03-02: retrieve_citation, ask_user (dual-mode), record_finding + tests

### Phase 4: Graph
**Goal**: The autonomous LangGraph loop — ReAct + Reflection + Agentic-RAG — with a bounded stop and a decision trace.
**Depends on**: Phase 3
**Success Criteria** (what must be TRUE):
  1. `pytest tests/e2e -q` exits 0 on a fixture doc using an in-memory store seeded from `data/fixtures`
  2. The run yields ≥1 finding, ≥1 retracted-or-asked span, and a non-empty decision trace
  3. The loop always stops within `AGENT_MAX_ITERS` (no infinite loop)
**Plans**: 2 plans

Plans:
- [ ] 04-01: state, nodes (perceive / reason-route / act / observe), bounded stop, trace
- [ ] 04-02: Reflection node + Agentic-RAG grounding/retract routing + e2e (structural-invariant asserts)

### Phase 5: Ingest
**Goal**: Build the ERIC retrieval corpus into local Chroma, offline.
**Depends on**: Phase 2
**Success Criteria** (what must be TRUE):
  1. `python -m inclusify_agent.ingest --sample 50 --embedder hash` builds a store with no network
  2. A `retrieve_citation` test returns ≥1 hit from the sample store
**Plans**: 1 plan

Plans:
- [ ] 05-01: streaming ERIC loader + chunker + embed→Chroma + `--sample` flag + retrieval test

### Phase 6: Report + Entrypoints
**Goal**: A cited, machine-checkable report and a CLI/API to produce it.
**Depends on**: Phase 4, Phase 5
**Success Criteria** (what must be TRUE):
  1. `python -m inclusify_agent.cli audit data/fixtures/sample.txt --provider mock` exits 0
  2. Output is schema-valid JSON with findings (each carrying a citation or marked "unverified") and a decision trace
**Plans**: 2 plans

Plans:
- [ ] 06-01: report schema + JSON/markdown renderer + trace
- [ ] 06-02: CLI (+ optional FastAPI) wiring graph + providers

### Phase 7: Eval + Ablation
**Goal**: Show the agent works and that its autonomy changes outcomes versus a fixed pipeline.
**Depends on**: Phase 6
**Success Criteria** (what must be TRUE):
  1. `python -m eval.run --mock` exits 0
  2. It prints control-flow divergence — the agent emits `ask`/`retract` events where the fixed-order baseline does not
  3. A gold-set harness exists (metrics are placeholders offline; real numbers are needs-keys)
**Plans**: 1 plan

Plans:
- [ ] 07-01: gold-set loader + metrics scaffold + fixed-pipeline baseline + ablation report

### Phase 8: Package
**Goal**: One-command offline demo, documented and lean.
**Depends on**: Phase 6, Phase 7
**Success Criteria** (what must be TRUE):
  1. `docker compose up` runs a demo audit on a bundled fixture and writes a report
  2. `ponytail-audit` prints a net leanness figure and a `ponytail-debt` ledger exists
  3. README documents offline + with-keys modes and a needs-keys checklist exists
**Plans**: 1 plan

Plans:
- [ ] 08-01: end-to-end compose demo + README + needs-keys checklist + ponytail audit/debt

## Progress

**Execution Order:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Scaffold | direct | Complete | 2026-06-20 (tag p1) |
| 2. Providers | direct | Complete | 2026-06-20 (tag p2) |
| 3. Tools | direct | Complete | 2026-06-20 (tag p3) |
| 4. Graph | direct | Complete | 2026-06-20 (tag p4) |
| 5. Ingest | direct | Complete | 2026-06-20 (tag p5) |
| 6. Report + Entrypoints | direct | Complete | 2026-06-20 (tag p6) |
| 7. Eval + Ablation | direct | Complete | 2026-06-20 (tag p7) |
| 8. Package | direct | Complete | 2026-06-20 (tag v0-offline) |

---
*Created 2026-06-19. Each phase's Success Criteria are the offline exit-checks from `docs/BUILD_PLAN.md` §6.*
