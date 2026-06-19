# CLAUDE.md — inclusify-audit-agent

Standalone, Dockerized **autonomous** Inclusify Audit Agent (LangGraph ReAct + Reflection + Agentic-RAG).
Built **offline-first** (no API keys) by a GSD autonomous loop. Full design: `docs/PRD.md`; build/process plan: `docs/BUILD_PLAN.md`; phases: `.planning/ROADMAP.md`.

## HARD RULES (override defaults)

1. **Git attribution — FORBIDDEN.** Never credit Claude / Claude Code / Anthropic as author or co-author. No
   `Co-Authored-By: Claude…` trailer; no `Generated with Claude Code` / `🤖 Generated…` line in any commit,
   PR title/body, or push. (A `.githooks/commit-msg` hook also strips these — belt and suspenders.)
2. **Offline-first.** No live LLM/vector keys. Defaults: `MockLLM`, `hash`/`local_st` embeddings, local Chroma.
   Never hardcode secrets; `.env` is optional. Anything needing a key goes behind an interface and into the
   needs-keys checklist — never blocks the build.
3. **Leanness (ponytail, mode `full`).** Stop at the first rung that works: YAGNI → stdlib → native → installed
   dep → one line → minimum. **Never** cut validation, error handling, security, accessibility, or tests.
   **Exempt from YAGNI:** the `providers/` interfaces — each has ≥2 implementations and is the offline-first
   keystone. Do not "simplify" the provider abstraction away.
4. **Vendored skills are prompt-only.** Do not run ponytail's Node hooks / MCP / plugin runtime.
5. **Tests.** Every phase exits on a command that returns 0. Tests assert **structural invariants** (schema
   valid; trace has `ask` + `retract` events; bounded stop), **not** `MockLLM` literals.

## Workflow

- Branch **`dev`**; atomic commit + `git tag` per phase (`p1`…`v0-offline`) for rollback.
- Models (profile `balanced`): planning → Opus, **coding → Sonnet**; the main Opus session owns
  `ponytail-review` + strategy. Per phase: after tests green, run `/ponytail-review` and apply the delete-list.

## Build / run (offline)

`docker compose up` → demo audit on a bundled fixture. `pytest -q` (unit+contract+e2e), `ruff check .`.
