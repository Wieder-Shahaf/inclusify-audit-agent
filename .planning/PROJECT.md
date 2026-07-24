# Inclusify Audit Agent

## What This Is

A standalone, Dockerized autonomous agent that audits **English** academic text (paper / syllabus /
guideline) for non-inclusive language. v2 architecture: **DocumentAuditor → parallel
EvidenceInvestigators → ReportConsolidator** (orchestrator-workers on LangGraph `Send` fan-out) —
the model reads full discourse context, writes its own evidence queries, escalates local-RAG →
live ERIC search, rejects/retracts what evidence can't support. Course deliverable for Technion
"AI Agent Systems" (spec: `docs/course/Project.pdf`); full design: `docs/PRD.md` v2.0.

## Core Value

Every finding ships the complete 5-field contract **in the main response**: verbatim quote
(code-verified offsets) · classification (7 categories, multi-label) · grounded why ·
the evidence example itself (cited, RAG or live search) · minimal inclusive rewrite.
Autonomy lives where decisions are contingent (what to flag, what evidence, when to escalate,
what to retract); control flow lives in code. Efficiency is architectural (course req #1):
no routing calls, doc read ≈ once, parallel fan-out, recurrence dedup, visible token ledger.

## Requirements

### Active (v2-redesign — R1…R7, see BUILD_PLAN §3)

- [ ] R1 Chunker + guards: blocks/sentences/windows with exact offsets; quote verification; English/size guards
- [ ] R2 Lexicon 44 → ≥1,500 sourced entries (`condition` + provenance); sensor-not-autoflag
- [ ] R3 Document gold (97-span annotated paper) + overlap P/R scorer; sentence gold loader
- [ ] R4 DocumentAuditor: per-window detection, every lexicon hint adjudicated, recurrence grouping
- [ ] R5 EvidenceInvestigator: bounded tool loop, corpus_search + ERIC Lucene ladder, parallel ≤5, confirm/reject
- [ ] R6 ReportConsolidator + report v2.0 + steps modules + regenerated architecture PNG + /api/why reroute
- [ ] R7 Calibration on both gold layers + budget ledger + <300 s Vercel verification + tag `v2-redesign`

### Out of Scope

- Hebrew (decided 2026-07-24 — never promised on a graded surface; clean rejection instead)
- Multi-document / corpus auditing (Supervisor envelope) — roadmap only
- Text generation / autonomous edits / production writes
- Span-level classification cache (add only if the ledger shows budget pressure)

## Constraints

- **Course spec:** fixed endpoints + `steps[]` schema; module names consistent across diagram/steps/descriptions;
  LLMod.ai `gpt-5.4-mini` + `text-embedding-3-small`; Pinecone + Supabase; Vercel ≤300 s/call; **$13 total**; due 23/8/2026.
- **Offline-first (hard rule):** full suite green with zero keys — MockLLM (audit/investigate/consolidate)
  + hash embeddings + seeded in-memory store.
- **Git:** branch `dev`, `feat/*` merged promptly; no Claude/Anthropic attribution ever (hard rule #1).
- **Leanness:** ponytail `full`; provider interfaces YAGNI-exempt; teardown human-only (hard rule #6).

## Key Decisions

| Decision | Rationale |
|---|---|
| Auditor–Investigator–Consolidator (v2) | fixed sequence in code, contingent judgment in the model; kills route rubber-stamping + sentence-isolation (0/38 gold problem spans are lexicon-reachable) |
| Windows (~1.8k tok) as the LLM unit, sentences for anchoring | Achva doctrine is a discourse judgment; quotes stay verbatim via offset-exact verification |
| Parallel fan-out + recurrence dedup | wall clock = slowest finding; 12-page gold paper ≈ 2 min ≪ 300 s |
| Lexicon as sensor at ≥1,500 terms | hits are hints the Auditor adjudicates; `condition` rides along — no auto-flag false positives |
| ERIC ladder compiled in code | API verified: full Lucene, no stemming; model supplies concepts, code guarantees syntax |
| Two-layer gold + within-doc negatives | 59 expert-approved spans on the same pages = honest FP measurement |
| Identical Auditor system prompt | provider KV-cache; "minimize context" served by architecture |
