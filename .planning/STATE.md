---
gsd_state_version: 1.0
milestone: v0
milestone_name: v0 Offline
status: in_progress
last_updated: "2026-06-19T00:00:00.000Z"
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md · Full design: docs/PRD.md · Build plan: docs/BUILD_PLAN.md

**Core value:** An autonomous agent that owns its control flow to audit academic text for non-inclusive
language and produce a citation-grounded, self-reviewed report.
**Current focus:** P0 bootstrap complete; ready to run Phases 1–8 via gsd-autonomous (offline, no keys).

## Accumulated Context

### Decisions
- P0: model profile `balanced` (planner→Opus, executor→Sonnet); main Opus session owns substantive review.
- P0: offline-first providers (MockLLM + hash/local embeddings + local Chroma); no API keys.
- P0: ponytail vendored prompt-only (pinned 0403c4d); `full` mode for executor; provider interfaces YAGNI-exempt.
- P0: no Claude/Anthropic git attribution (CLAUDE.md §1 + .githooks/commit-msg).

### Roadmap Evolution
- v0 Offline milestone seeded from docs/PRD.md + docs/BUILD_PLAN.md (8 phases).
