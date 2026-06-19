# Inclusify Audit Agent

## What This Is

A standalone, Dockerized **autonomous agent** (LangGraph ReAct + Reflection + Agentic-RAG) that audits a single
academic document (paper / syllabus / slide text) for non-inclusive language and produces a defensible,
citation-grounded, self-reviewed report. Submitted as the deliverable for the Technion "AI Agent Systems"
course (idea #1, Inclusify); later integrable into the Inclusify product. Full spec: `docs/PRD.md`.

## Core Value

Unlike a fixed pipeline, the agent **owns its control flow**: it decides per span whether to do a cheap
lexicon check, escalate to deeper analysis, ground a flag in an authoritative source (retracting what it
cannot ground), or ask a clarifying question — then reflects before finalizing. Autonomy is the deliverable.

## Requirements

### Active (v0 Offline — autonomous build, no API keys)

- [ ] Offline-first provider abstraction (LLM / embeddings / vector store) with mock + local defaults
- [ ] 7 tools: chunk, lexicon_lookup, classify_span, retrieve_citation, propose_rewrite, ask_user, record_finding
- [ ] LangGraph ReAct loop + Reflection node + Agentic-RAG grounding + bounded stop + decision-trace
- [ ] ERIC corpus ingestion → local Chroma
- [ ] Cited report (schema + renderer) + CLI/API
- [ ] Eval harness + agent-vs-pipeline ablation (control-flow capability, offline)
- [ ] End-to-end Docker offline demo + needs-keys checklist

### Out of Scope (this milestone)

- Multi-document / corpus auditing (Supervisor envelope) — documented roadmap
- Live gpt-5-mini / Azure embeddings / real eval metrics — needs-keys, deferred
- Text generation; autonomous edits; any production write

## Constraints

- **No API keys** — must build and test fully offline (mock LLM, local embeddings, local Chroma).
- **Course stack** — gpt-5-mini / Azure OpenAI / LangChain when keys arrive; ≤ 50 MB data/domain.
- **Standalone + Docker**; Python 3.11; CPU-only.
- **Git**: no Claude/Anthropic attribution in commits/PRs (see CLAUDE.md §1).
- **Leanness**: ponytail `full` for the executor; provider interfaces exempt from YAGNI.

## Key Decisions

| Decision | Rationale |
|---|---|
| LangGraph orchestration | explicit ReAct loop + Reflection node + decision-trace = the autonomy evidence |
| Offline-first providers | no keys → mock LLM + local embeddings + Chroma; contract tests keep mock/real interchangeable |
| `balanced` model profile | planner→Opus, executor→Sonnet (matches intent); main Opus session owns substantive review |
| ponytail (prompt-only, pinned) | counters Sonnet over-building; review gate per phase |
| MockLLM drives all nodes | deterministic classify + route + reflect → reproducible e2e + stable trace |
