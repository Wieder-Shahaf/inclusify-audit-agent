# Build Plan — `inclusify-audit-agent` (v0.3, governs the v2 redesign)

**Companion to:** `docs/PRD.md` v2.0 (the *what*). This is the *how*: phase plan with offline exit
checks, what survives from v1, testing strategy, and standing process rules.

**History:** v0-offline (8 GSD phases, tag `v0-offline`) and v1-course-api (live stack + endpoints,
tag `v1-course-api`) are **complete**; their detailed plan is this file @ `v1-course-api` in git.
Standing rules from that era still govern (§4).

---

## 1. Objective

Rebuild the agent core to the v2 architecture — **DocumentAuditor → parallel EvidenceInvestigators
→ ReportConsolidator** on LangGraph (`Send` fan-out) — while keeping the endpoint contract, provider
abstraction, offline-first guarantee, and eval harness. Every phase exits on a command returning 0
with **zero API keys**; live checks are isolated in R7.

## 2. What survives v1 untouched vs. what changes

| Survives (do not rewrite) | Changes |
|---|---|
| `providers/` — llm (mock, openai_compat) · embeddings (hash, local_st, openai_compat) · vectorstore (inmemory, chroma, pinecone) · persistence (null, supabase) | `graph/` — nodes/edges replaced (perceive → audit → Send fan-out → consolidate → report); route node deleted |
| `server/app.py` endpoint contract + GUI + `RecordingLLM` mechanism | `MODULE_BY_TASK` → `{audit, investigate, consolidate}`; agent_info examples precomputed |
| `tools/retrieve_citation.py` (over-fetch ×5 + dedup) | `tools/chunk.py` → `parse()` (blocks/sentences/windows, offset-exact); `classify_span`/`propose_rewrite` folded into Auditor/Investigator prompts |
| `tools/eric_live_search.py` env-gate + never-raise | gains the compiled Lucene query ladder + `{phrases, any_of, min_year}` contract |
| eval harness structure (`eval/run.py`, `gold.py`, `achva.py`) | gains the document-level gold + overlap scorer |
| CLI / Docker / Vercel entrypoints | report schema → v2.0 (5-field contract per finding) |
| MockLLM keystone pattern | new scripted tasks: `audit`, `investigate`, `consolidate` |

## 3. V2 phase plan (each exit runs offline unless marked LIVE)

| Phase | Deliverable | Exit check (returns 0) |
|---|---|---|
| **R1 Chunker + guards** | `parse(text) → (blocks, sentences, windows)` with char offsets; abbreviation-guarded sentence split; window packing (~1.8k tok, heading path, last-¶ overlap); quote-verification helper (exact + whitespace-normalized offset map); guards (empty / non-Latin / >40 windows) | `pytest tests/unit/test_parse.py -q` — offsets round-trip on fixtures incl. the gold paper's fulltext; guard cases covered |
| **R2 Lexicon expansion** | `scripts/build_lexicon.py`: retext-equality YAML (MIT) + INI + Tiny Heap occupations + curated APA/NCDJ/GLAAD CSVs → bundled JSON `{term, category, alternatives, note, condition, source}`; provenance table in README | `python scripts/build_lexicon.py && pytest tests/unit/test_lexicon.py -q` — ≥1,500 entries, schema-valid, `condition` carried, whole-doc scan < 100 ms on gold fulltext |
| **R3 Gold assets + scorer** | `data/gold/achva/doc_gold.json` (fulltext + 97 deduped spans, char offsets, label sets) built from the annotated PDF; overlap scorer (≥50 % char overlap; label ∈ gold set); review_set loader | `python -m eval.run --gold doc --mock` exits 0 and prints span P/R/F1 + FP-rate-on-correct (mock numbers are placeholders; the *harness* is the deliverable) |
| **R4 DocumentAuditor** | auditor prompt (doctrine + fixed English Achva exemplars, identical across calls); per-window call; candidate JSON parsing + repair retry; verbatim quote verification; overlap dedupe; recurrence grouping; MockLLM `audit` task | `pytest tests/e2e/test_audit_v2.py -q` — fixture doc yields verified-offset candidates; every lexicon hint adjudicated; bounded windows |
| **R5 EvidenceInvestigator** | tool loop (≤4 turns; native tool-calls, JSON-action fallback); `corpus_search` + `live_search` ladder; parallel `Send` fan-out (≤5); confirm/reject verdicts; MockLLM `investigate` script (incl. one scripted reject + one escalation) | `pytest tests/e2e -q` — trace shows ≥1 model-written query, ≥1 reject, escalation path exercised, all loops within bounds, zero network (live_search gated off) |
| **R6 Consolidator + report** | consolidation prompt (retract-with-rationale, patterns, severity); report v2.0 renderer (markdown + JSON); `steps[]` modules wired; architecture PNG regenerated; agent_info precomputed; `/api/why` rerouted to single-finding Investigator | `pytest -q` (full suite) + `python -m inclusify_agent.cli audit data/fixtures/sample.txt --provider mock` emits schema-valid v2.0 report; diagram module names == `MODULE_BY_TASK` values |
| **R7 Calibration + live (LIVE)** | Achva P/R on both gold layers with live providers; threshold/prompt tuning; budget ledger in Supabase + GUI; latency check on the gold paper (<300 s); Vercel deploy; README metrics table; v1-tag ablation row | `python -m eval.run --gold all --live` prints the metrics table; `/api/execute` on Vercel with the gold paper < 300 s; tag `v2-redesign` |

Rollback: atomic commit + tag per phase (`r1`…`r7`), same convention as v0/v1.

## 4. Standing process rules (unchanged, still binding)

- **Offline-first is a hard rule:** MockLLM + `hash` embedder + seeded in-memory store must drive
  the *entire* v2 graph; the full suite stays green with zero keys. Anything needing keys lives in
  R7 + `docs/NEEDS_KEYS.md`.
- **Git:** branch `dev`, short-lived `feat/*` merged promptly; **no Claude/Anthropic attribution**
  anywhere in commits/PRs (CLAUDE.md hard rule #1 + `.githooks/commit-msg`).
- **Leanness:** ponytail `full`; provider interfaces remain YAGNI-exempt; per-phase
  `ponytail-review` before closing.
- **Destructive teardown is human-only** (CLAUDE.md hard rule #6).

## 5. Testing strategy (v2 invariants)

unit (parse offsets, lexicon schema/speed, ladder compilation, quote verification) ·
contract (providers unchanged; MockLLM determinism for the three new tasks) ·
e2e (offline full-graph run) · eval (gold harness).

**Anti-tautology — e2e asserts structural invariants, never MockLLM literals:**
report schema-valid; every finding's quote verbatim-verifiable at its offsets; trace contains
≥1 investigator **reject** and ≥1 consolidator **retract** (seeded by the mock script);
≥1 model-written query string in the trace; every investigation ≤4 turns; windows ≤ cap;
lexicon hints all adjudicated (hint count == adjudication count); clean-doc run makes
0 investigator/consolidator calls.

## 6. Definition of Done (v2)

`pytest -q` green with no keys; `python -m eval.run --gold doc --mock` green;
live metrics table (both gold layers) in README; gold-paper audit on Vercel < 300 s with the
budget ledger visible; architecture PNG / `steps[]` / descriptions using the same three LLM module
names; tag `v2-redesign` pushed.
