---
gsd_state_version: 1.0
milestone: v0
milestone_name: v0 Offline
status: complete
last_updated: "2026-06-20T20:00:00.000Z"
progress:
  total_phases: 8
  completed_phases: 8
  total_plans: 0
  completed_plans: 0
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md · Full design: docs/PRD.md · Build plan: docs/BUILD_PLAN.md

**Core value:** An autonomous agent that owns its control flow to audit academic text for non-inclusive
language and produce a citation-grounded, self-reviewed report.
**Current focus:** v0-offline milestone complete (all 8 phases green; tag `v0-offline`).
**Next:** wire course Azure when keys land (see docs/NEEDS_KEYS.md), or refine live-providers
quality against the work-VM.

## Accumulated Context

### Decisions
- P0: model profile `balanced` (planner→Opus, executor→Sonnet); main Opus session owns substantive review.
- P0: offline-first providers (MockLLM + hash/local embeddings + local Chroma); no API keys.
- P0: ponytail vendored prompt-only (pinned 0403c4d); `full` mode for executor; provider interfaces YAGNI-exempt.
- P0: no Claude/Anthropic git attribution (CLAUDE.md §1 + .githooks/commit-msg).
- P0+: lean-build chosen over the full gsd-autonomous subagent ceremony — BUILD_PLAN was already specified;
  direct implementation per-phase with atomic commits + git tags + per-phase exit checks.
- P2: live providers wired alongside offline defaults (OpenAICompatLLM, OpenAICompatEmbeddings,
  QdrantStore) so the work-VM endpoint switch is `.env`-only.
- P4: LangGraph state machine (perceive → route ↔ act → reflect → stop); MockLLM owns the
  scripted ReAct election deterministically. Reflection drops low-confidence findings;
  agentic-RAG routes to ask_user when retrieval is weak.
- P5: ERIC corpus stays gitignored + streaming-only (~42MB); lexicon moved INTO the package
  (`src/inclusify_agent/data/`) so `pip install` carries it.
- P8: scripts/teardown_vm.sh self-gates on interactive TTY + typed `y` — yolo/auto cannot
  trigger destructive teardown (CLAUDE.md hard rule #6).

### Roadmap Evolution
- v0 Offline milestone seeded from docs/PRD.md + docs/BUILD_PLAN.md (8 phases).
- All 8 phases complete with per-phase tags (p1…p8) and final v0-offline tag.
- 76 tests pass offline (unit + contract + e2e + smoke). 0 keys required.
- `python -m eval.run --mock` exits 0 and reports `agent_only_event_types=["retract"]` —
  control-flow divergence proven.
