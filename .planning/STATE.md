---
gsd_state_version: 1.0
milestone: v2
milestone_name: v2 Redesign (Auditor–Investigator–Consolidator)
status: complete
last_updated: "2026-07-24T00:00:00.000Z"
progress:
  total_phases: 7
  completed_phases: 7
  total_plans: 0
  completed_plans: 0
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md · Full design: docs/PRD.md (v2.0) · Build plan: docs/BUILD_PLAN.md §3

**Core value:** An agent that audits English academic text like an expert reviewer — reads full
discourse context, seeks its own evidence (local RAG or live ERIC search), rejects/retracts what it
can't support — and delivers the 5-field contract per finding: verbatim quote · classification ·
grounded why · evidence example · inclusive alternative.
**Current focus:** v2-redesign COMPLETE (2026-07-24, tag `v2-redesign`, main @ 1e7b576) — R1-R7
all merged via reviewed PRs (#10-#18), production on Vercel verified serving the v2 chain.
Live-calibrated: sentence-level F1 0.911 (ablation baseline 0.367); doc-level span R 0.25 / P 0.12
reported honestly in README with characterized causes. 259 offline tests.
Next: Supabase RLS insert policy (human task); optional post-course: more annotated gold docs,
taxonomy alignment, selectivity dial.
**Carry-over from v1:** Supabase RLS insert policy still pending (human task); Vercel deploy live
and verified; LLMod.ai + Pinecone wired.

## Accumulated Context

### Decisions (v2, 2026-07-24 — full log in PRD §14)
- Architecture: DocumentAuditor (per-window detection) → parallel EvidenceInvestigators (bounded
  evidence tool-loops, LangGraph Send, ≤5 concurrent, ≤4 turns) → ReportConsolidator. Route-LLM
  and per-sentence classification removed; control flow is code, judgment is model.
- English-only scope; non-Latin input rejected cleanly.
- Lexicon: sensor-not-autoflagger; expand 44 → ≥1,500 via build_lexicon.py (retext-equality MIT
  backbone + INI + APA/NCDJ/GLAAD curation + Tiny Heap occupations); `condition` field carried
  into Auditor hints.
- ERIC live search: code-compiled Lucene ladder (strict→relaxed→broad), model supplies concepts;
  API verified 2026-07-24 (full Lucene, no stemming, peerreviewed:T, year ranges).
- Gold: document-level 2018-03783-002 (97 annotation-extracted spans, 59 correct + 38 problems,
  5 multi-label) + sentence-level review_set (50 EN). Overlap ≥50% matching; label ∈ gold set.
- Recurrence dedup: one investigation per framing; Consolidator reports patterns.
- Module names locked: DocumentAuditor / EvidenceInvestigator / ReportConsolidator
  (+ Chunker, LexiconScanner, CorpusSearch, LiveSearch in the diagram).
- /api/why kept = single-finding EvidenceInvestigator (optional interactivity credit).
- Offline-first preserved: MockLLM gains audit/investigate/consolidate scripted tasks.

### v0/v1 record
- v0-offline: 8 phases, 76 offline tests, tags p1…p8 + v0-offline (2026-06-20).
- v1-course-api: endpoints + GUI + LLMod.ai/Pinecone/Supabase live stack, Vercel deploy verified,
  batch1_3 baked in (tag v1-course-api). v1 decisions preserved in STATE.md @ v1-course-api.
