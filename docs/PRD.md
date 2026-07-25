# Inclusify Audit Agent — Technical PRD (v2.0)

**Course:** AI Agent Systems (Technion 00960237), Spring 2026
**Team:** Shahaf Wieder (318159506) · Barak Sharon (207283888)
**Governs:** the v2 redesign (milestone `v2-redesign`). v0-offline and v1-course-api are complete
(tags `v0-offline`, `v1-course-api`); their PRD is preserved in git history (`docs/PRD.md` @ `v1-course-api`).
**Course spec:** `docs/course/Project.pdf` — endpoints, `steps[]` schema, LLMod.ai models, Vercel,
$13 budget, 300 s/call cap, due **23/8/2026**.

---

## 1. Problem & product contract

**Input:** raw English academic text — a paper, syllabus, or guideline (pasted into `POST /api/execute`).

**Output — per finding, all five fields, in the main response (not behind a button):**

| # | Field | Guarantee |
|---|---|---|
| 1 | **Quoted problematic text** | verbatim quote, code-verified against the source, exact char offsets |
| 2 | **Classification** | one of 7 categories; multi-label allowed (primary + optional secondary) |
| 3 | **Explanation (why)** | grounded in retrieved evidence, cites it inline `[1]` |
| 4 | **Grounding example** | the evidence snippet itself — from local RAG (ERIC corpus) *or* live ERIC search — with title / year / URL |
| 5 | **Inclusive alternative** | minimal-edit rewrite that preserves technical meaning; lexicon alternatives preferred |

Plus per-finding `confidence` (`high/medium/low`) and `needs_human_review`, and a document-level
summary of recurring patterns.

**Categories** (aligned with the Achva expert legend + lexicon):
`gendered · exclusionary · ableist · outdated · factually-incorrect · potentially-offensive · biased`.

**Scope: English only** (decided 2026-07-24). Hebrew was never promised on any graded surface;
non-Latin-dominant input gets a clean human-readable rejection. The evidence stack (ERIC, lexicon,
SBIC) is English; scoping the claim keeps every claim measured.

---

## 2. Why v2 — what v1 got wrong

v1 (per-sentence ReAct with an LLM router) had three structural defects, all measured:

1. **Route rubber-stamping.** An LLM call before *every* tool step confirmed a decision `act()` had
   already made deterministically — ~half of all calls; against a live model it doubles cost and
   violates course requirement #1 ("avoid unnecessary LLM calls").
2. **Sentence-isolated judgment.** The Achva doctrine — flag when the *subject* of the sentence is a
   harmful view; skip when the subject is the correction — is a **discourse** judgment. Our gold
   document proves it: **0 of its 38 expert-flagged spans contain a lexicon trigger**; they are
   framings ("gender-atypical", "gay culture") judgeable only in context. ±80 chars of context
   cannot hold both recall and precision.
3. **The contract fields weren't in the main flow.** Explanation + grounding lived behind the
   optional `/api/why` button; the required output is *the* audit response.

Latency was the forcing function: ~115 serial LLM calls on a 30-sentence document ≈ 3–6 min —
brushing Vercel's hard 300 s cap. Cost degrades gracefully; a serverless timeout returns nothing.

**The v2 inversion: fixed sequence in code, contingent judgment in the model.** The phase order
(perceive → detect → verify → report) is fixed — any competent agent would rediscover it every run
at our expense. Everything *inside* is decided by the model at runtime.

---

## 3. Agentic behavior — where autonomy actually lives

A pipeline is a system where the number and sequence of LLM calls is known before the run.
In v2, only the phase *order* is known; the model decides at runtime:

| Runtime decision | Made by | Visible in `steps[]` as |
|---|---|---|
| Which spans are candidates (incl. implied bias with no trigger) | DocumentAuditor | per-window candidate sets that differ per input |
| How many Investigators spawn (fan-out is input-dependent) | Auditor output → LangGraph `Send` | variable number of `EvidenceInvestigator` runs |
| What evidence would prove/refute a finding — the search query itself | EvidenceInvestigator | model-written queries |
| Is local evidence sufficient? escalate to live ERIC search? | EvidenceInvestigator | variable-length tool loops (2–4 turns) |
| Confirm or **reject** its own candidate | EvidenceInvestigator | rejections with rationale |
| Retract / merge / pattern-group across findings | ReportConsolidator | retractions with rationale |

This is the **orchestrator–workers** pattern with evaluator loops: agency exactly where decisions
are contingent, deterministic code where thinking adds nothing. The trace evidences autonomy by
*content* (different queries, different escalations, different verdicts per input), not by an LLM
narrating a fixed itinerary.

---

## 4. Architecture

```
POST /api/execute {"prompt": raw English academic text}
        │
  [0] GUARDS ─────────────────── code · no LLM
        │   empty → error · non-Latin-dominant → "English only" error
        │   > ~10 windows → "document too large" error (300 s guard)
        ▼
  [1] PERCEIVE (Chunker) ─────── code · no LLM
        │   blocks (heading/list/paragraph, char offsets)
        │   sentences (abbreviation-guarded split, offsets)
        │   windows (~1,800 tok, whole blocks, heading path, last-¶ overlap)
        │   LexiconScanner: one whole-doc scan → hits pinned to windows
        ▼
  [2] DocumentAuditor ────────── LLM · 1 call/window · windows in parallel
        │   in : window text + heading path + lexicon hits as SENSOR HINTS
        │        (must adjudicate every hint; hunt implied bias by reading)
        │   out: candidates [{quote, category, initial_reason, lexicon_backed}]
        │   code: verbatim-verify quotes → absolute offsets → attach
        │         sentence + paragraph → dedupe overlap zone → recurrence-group
        │   0 candidates → [5] clean bill
        ▼
  [3] EvidenceInvestigator ───── LLM tool-loop · PER FRAMING · parallel ≤5
        │   context: quote ⊂ sentence ⊂ paragraph + category + lexicon alts
        │   tools: corpus_search (Pinecone/Chroma over ERIC)
        │          live_search  (ERIC API, compiled query ladder, env-gated)
        │   loop : write query → read snippets → sufficient? finalize
        │          : weak → escalate → re-judge   (≤4 LLM turns, hard bound)
        │   out  : verdict confirm/reject · final category (+secondary)
        │          explanation citing [n] · evidence{title,year,url,snippet}
        │          minimal rewrite · confidence · needs_human_review
        ▼
  [4] ReportConsolidator ─────── LLM · 1 call · skipped if 0 confirmed
        │   dedupe/nested spans · cross-finding consistency ·
        │   retract-with-rationale · document patterns · severity order
        ▼
  [5] REPORT ───────────────────  code · no LLM
            markdown: per-finding 5-field contract + doc summary + patterns
            steps[] = every LLM call {module, prompt{System_prompt,User_prompt}, response}
            Supabase run log (prompt, status, response, steps, token usage)
```

**Recurrence rule** (matches expert behavior in the gold doc, where the same framing is flagged on
pp. 1, 2, 3, 7, 9): the Investigator runs **once per distinct framing**; its verdict applies to all
occurrences, which the Consolidator reports as one pattern with N locations. On the gold paper this
cuts ~38 investigations to ~20.

**Module names** (course spec §C — must match across diagram, `steps[]`, descriptions):
LLM modules `DocumentAuditor` · `EvidenceInvestigator` · `ReportConsolidator`;
non-LLM modules `Chunker` · `LexiconScanner` · `CorpusSearch` · `LiveSearch`.
`POST /api/why` = a single-finding `EvidenceInvestigator` run (kept as the optional
back-and-forth interaction credit).

---

## 5. Chunking mechanism (offset-exact, two consumers)

Two units for two consumers: **windows** for the Auditor (discourse context), **sentences** for
anchoring (verbatim quotes, rewrite scope). Sentences are never the LLM call unit.

1. **Block parse** — split on blank lines; classify heading / list / paragraph by cheap
   heuristics; every block carries `char_start/end` into the *unmodified* raw string. Hard-wrapped
   lines need no unwrapping (later stages treat `\s+` as one separator).
2. **Sentence segmentation** — split after `[.!?…]` + whitespace when the previous token is not in
   a ~15-entry academic abbreviation list (`Dr, Prof, et al, e.g., i.e., vs, cf, Fig, Eq, pp, No…`)
   and the next char is `[A-Z"'(0-9]`.
3. **Window assembly** — greedy-pack whole blocks to ~1,800 est. tokens (words × 1.3); prefer
   breaking at headings; never mid-paragraph (oversized paragraph → sentence-boundary fallback).
   Overlap = repeat the previous window's last paragraph; findings dedupe by absolute offsets.
   Windows carry heading path + their lexicon hits.
4. **Quote verification** — every Auditor quote is re-found in the raw text: exact match, then
   whitespace-normalized fuzzy match via an offset map. Unverifiable quote → re-quote or drop.
   Guarantees contract field #1 is verbatim.

Sizing: 10-page syllabus ≈ 6.5k tokens → 4–5 windows; the 12-page gold paper ≈ 15k tokens →
9–10 windows. Cap 10 windows/request with a clean error (live-recalibrated 2026-07-25: audits
run sequentially at ~10 s/window, so 40 windows could not finish inside Vercel's 300 s cap;
10 still covers the gold paper. `AGENT_MAX_WINDOWS` raises it where no serverless timeout applies).

`Chunk` is replaced by three dataclasses: `Block`, `Sentence`, `Window` (`tools/schemas.py`).

---

## 6. Tools

| Tool | Kind | Contract | Activation |
|---|---|---|---|
| `parse` (Chunker) | code | `str → (blocks, sentences, windows)` | always, once |
| `lexicon_lookup` | code | doc text → `LexiconHit[]` (term, category, alternatives, note, **condition**, source) | always, once, whole doc — **sensor, never auto-flag** |
| `audit_window` | LLM | window + hints → candidate list (JSON array) | per window |
| `corpus_search` | code (RAG) | model-written query → embed → Pinecone/Chroma → over-fetch ×5 → dedup by doc → top-3 `Citation` | Investigator's choice |
| `live_search` | code (ERIC API) | `{phrases[], any_of[], min_year}` → compiled Lucene ladder (below) → embed-rerank → top-3 | Investigator's choice; env-gated `ERIC_LIVE_SEARCH`; never raises |
| `investigate` | LLM loop | candidate + evidence turns → verdict/explanation/evidence/rewrite | per distinct framing, parallel ≤5, ≤4 turns |
| `consolidate` | LLM | confirmed findings (compact) → kept/retracted/patterns | once, if any confirmed |
| `render_report` | code | state → markdown + JSON + steps | always |

**ERIC query ladder** (verified against the live API 2026-07-24 — full Lucene support, **no
stemming**: `stereotype` 1,982 vs `stereotypes` 18,579): the model supplies concepts; *code*
compiles the query (LLM-written raw Lucene → silent syntax failures):

```
rung 1 strict : "phrase" AND (variants OR'd) AND peerreviewed:T AND publicationdateyear:[min TO now]
rung 2 relaxed: drop peerreviewed + field scoping; keep phrases; auto-expand plural variants
rung 3 broad  : category keywords only
stop at first rung with ≥3 hits → rows=10 with descriptions → embed-rerank vs finding → top-3
```

The same ladder upgrades `scripts/fetch_eric.py` corpus growth (`data/eric/queries.txt` gains
`peerreviewed:T`, year ranges, variant ORs).

---

## 7. Data assets

| Asset | Role | v2 change |
|---|---|---|
| **ERIC corpus** (~42 MB, 21,870 chunks; live: Pinecone `inclusify-eric`) | grounding retrieval | unchanged; ingest queries upgraded via the ladder |
| **Lexicon** | deterministic sensor | **expand 44 → ≥1,500 entries** via `scripts/build_lexicon.py`; schema gains `condition` + `source` |
| **Achva expert data** | gold + few-shots | English half only; fixed curated exemplars in the Auditor prompt (identical across calls → provider KV-cache) |
| **SBIC v2** | — | stays dropped (v1 decision holds) |

**Lexicon expansion sources** (verified 2026-07-24):

| Source | Size | License | Covers |
|---|---|---|---|
| retext-equality `data/en/` (9 YAML files, 77 KB — probed live) | ~1,400+ term forms, with alternatives **and context conditions** | MIT | backbone: gender, ablist, lgbtq, race, condescending, suicide, misc |
| Inclusive Naming Initiative | ~50 tiered terms | CC-BY | CS/tech terms (master/slave, whitelist, sanity check) — Technion syllabi will hit these |
| APA bias-free language guidelines (7th ed) | ~120–150 curated pairs | cite-and-curate | *the* academic authority; doubles as RAG material |
| NCDJ Disability Language Style Guide | ~80–100 | cite-and-curate | deepens `ableist` |
| GLAAD Media Reference | ~50 | cite-and-curate | exactly the Achva domain (outdated identity terms) |
| Tiny Heap affixed-words | ~700 occupation pairs | attribution | `-man/-woman` occupational forms |

At ≥1,500 terms false-positive pressure explodes ("crazy fast algorithm" is not ableist usage) —
absorbed by design: the lexicon **never flags on its own**; every hit is adjudicated in context by
the Auditor, with the `condition` note riding along in the hint.

---

## 8. Efficiency & budget (course requirement #1)

| Lever | Mechanism |
|---|---|
| No routing calls | control flow is code; LLM calls only where judgment is contingent |
| Doc read ≈ once | windows, not per-sentence prompts (v1 resent a 1.4k-token system prompt per sentence) |
| Identical Auditor system prompt | fixed curated exemplars → provider KV-cache across windows and runs |
| Parallel fan-out | investigations are independent; wall clock = slowest finding, not the sum |
| Recurrence dedup | one investigation per framing, verdict applied to all occurrences |
| Skip-if-empty | no Consolidator call on clean docs; no Investigators without candidates |
| Precomputed examples | `agent_info` prompt_examples served static (v1 re-ran 2 audits per Vercel cold start) |
| Budget ledger | token usage per call summed into the Supabase `audit_runs` row; visible in GUI |
| Bounds | ≤4 turns/investigation · ≤5 concurrent · ≤10 windows · JSON-repair retry ≤1 |

**Expected profile** (gpt-5.4-mini via LLMod.ai): 3-page syllabus ≈ **~17 small calls, ~30–45 s**;
the 12-page gold paper ≈ **~60–70 calls, ~2 min** — inside the 300 s cap with margin; ~1,000
audits inside the $13 budget. v1 baseline for the same syllabus: ~115 serial calls, 3–6 min.

---

## 9. Output schema (report v2.0)

```json
{
  "version": "2.0", "language": "en",
  "summary": { "windows": 4, "candidates": 9, "confirmed": 6, "rejected": 2,
               "retracted": 1, "needs_human_review": 1, "tokens": {"in": 28000, "out": 5100} },
  "patterns": [ { "framing": "generic 'he' for instructors", "category": "gendered",
                  "occurrences": 3, "locations": [[210,212],[1480,1482],[2205,2207]] } ],
  "findings": [{
    "id": "f01", "quote": "The chairman will hold office hours weekly.",
    "offsets": [204, 247], "sentence_offsets": [204, 247],
    "category": "gendered", "secondary_category": null,
    "explanation": "Occupational titles marked for gender signal exclusion in academic settings [1].",
    "evidence": [{ "source": "eric", "id": "EJ…", "title": "…", "year": 2021,
                   "url": "https://eric.ed.gov/?id=EJ…", "snippet": "…", "score": 0.61 }],
    "rewrite": "The chair will hold office hours weekly.",
    "confidence": "high", "grounded": true, "needs_human_review": false,
    "verdict_rationale": "confirmed: strong local corpus support",
    "occurrences": 1
  }],
  "steps_modules": ["DocumentAuditor", "EvidenceInvestigator", "ReportConsolidator"]
}
```

`response` (course contract) = the markdown rendering of this; `steps[]` = every LLM call.

---

## 10. Evaluation — three gold layers, all measured

| Layer | Asset | Tests | Metric |
|---|---|---|---|
| Sentence judgment | `review_set.jsonl` — 50 English expert-labeled sentences | doctrine precision (half are **Correct** text about sensitive topics) | label accuracy, FP rate on Correct |
| **Document-level, end-to-end** | **`2018-03783-002` gold paper** — 97 expert highlights: 59 correct (green) + 38 problems (15 biased, 11 potentially-offensive, 11 outdated, 1 factually-incorrect), 5 spans multi-label | the whole loop: windowing, detection, recurrence, precision against expert-approved spans | span-level P/R/F1 with **≥50 % char-overlap matching**; label counted correct if prediction ∈ gold label set; FP rate on the 59 correct spans |
| Offline regression | `data/fixtures/` + MockLLM | structural invariants, no keys | pytest green |

Extraction is annotation-based (PDF `/Highlight` objects with QuadPoints + RGB → legend colors),
not OCR — lossless. Gold asset: `data/gold/achva/doc_gold.json` (clean fulltext + deduped spans +
char offsets + label sets); scorer in `eval/`.

Also reported: grounded-rate (% findings with evidence), retraction count, tokens + est. cost per
audit (ledger), wall-clock. Ablation: v2 vs the v1 tag on the same gold assets.

---

## 11. Course-spec compliance map

| Spec item | v2 answer |
|---|---|
| `GET /api/team_info` / `agent_info` / `model_architecture` / `POST /api/execute` | unchanged contract; agent_info examples precomputed; architecture PNG regenerated from the v2 module set (`scripts/gen_architecture.py`) |
| `steps[]` = every LLM call, module names consistent | `RecordingLLM` unchanged; `MODULE_BY_TASK = {audit: DocumentAuditor, investigate: EvidenceInvestigator, consolidate: ReportConsolidator}` |
| Efficiency / prompt size / $13 | §8 — architecture-level, plus the visible ledger |
| Vercel ≤300 s | parallel fan-out + window cap + guards (§4 [0]) |
| Models | LLMod.ai `MB5R2CF-azure/gpt-5.4-mini` + `text-embedding-3-small` (wired, verified) |
| Databases | Pinecone (ERIC vectors) · Supabase (run log + ledger; verified end-to-end in production 2026-07-25 — see docs/NEEDS_KEYS.md) |
| GUI | unchanged (textarea → Run → response + steps); optional interactivity = `/api/why` |
| Offline-first (repo hard rule) | MockLLM gains `audit`/`investigate`/`consolidate` scripted tasks; hash embedder + seeded store; full suite green with zero keys |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| LLMod strips native tool-calls | Investigator falls back to a JSON-action protocol — same loop, same trace shape (verify in R5 day one) |
| Long-doc recall dilution | 1.8k windows + overlap + lexicon floor (every hint adjudicated) + optional "what did you miss?" sweep pass if gold recall < target |
| Quote hallucination | code-side verbatim verification; unverifiable → re-quote or drop |
| Parallel rate limits | concurrency 5; graceful serial degradation |
| Pinecone/LLM outage | existing fallbacks (seeded in-memory store; human-readable error contract) |
| Model pins temperature (observed on gpt-5.4-mini) | determinism via strict JSON schemas + repair retry, not sampling knobs |

---

## 13. Milestone plan (v2-redesign) — detail in `docs/BUILD_PLAN.md` §V2

R1 Chunker+guards → R2 Lexicon expansion → R3 Gold assets+scorer → R4 DocumentAuditor →
R5 EvidenceInvestigator (+ERIC ladder, parallel fan-out) → R6 Consolidator+report+diagram →
R7 Calibration+live verification+deploy. Each phase exits on an offline command returning 0;
R7 adds the live-key checks. Due date 23/8/2026; ~4.5 weeks available.

---

## 14. Decision log

| Date | Decision |
|---|---|
| 2026-06-19 | v0/v1 decisions (LangGraph; offline-first; Achva gold; SBIC dropped; ask_user dual-mode) — see PRD @ `v1-course-api` |
| 2026-07-24 | **v2 redesign**: Auditor–Investigator–Consolidator (orchestrator-workers); route-LLM and per-sentence classification removed; explanation+grounding move into the main response |
| 2026-07-24 | **English-only scope**; non-Latin input rejected with a clear message |
| 2026-07-24 | Lexicon 44 → ≥1,500 via sourced build script; lexicon is a sensor, never an auto-flagger |
| 2026-07-24 | ERIC live search = code-compiled Lucene ladder (API verified: full Lucene, no stemming) |
| 2026-07-24 | Document-level gold = 2018-03783-002 (97 annotation-extracted spans); overlap-based scoring; multi-label sets |
| 2026-07-24 | Recurrence dedup: investigate once per framing; Consolidator reports patterns |
| 2026-07-24 | `/api/why` retained as single-finding Investigator (optional interactivity credit) |
| 2026-07-24 | Module names locked: DocumentAuditor / EvidenceInvestigator / ReportConsolidator (+ Chunker, LexiconScanner, CorpusSearch, LiveSearch in the diagram) |
