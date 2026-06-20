# AI Agent — Technical PRD (DRAFT v0.1)

**Course:** AI Agent Systems (Technion 00960237), Spring 2026
**Team:** Shahaf Wieder (318159506) · Barak Sharon (207283888)
**Deliverable:** Week-7 "AI Agent Technical PRD"
**Selected idea:** #1 — **Inclusify** (Curriculum Inclusivity Auditor, Higher-Education domain)

> Status: working draft for team review. Sections marked **[OPEN]** still need a decision. The final
> submission should be exported following the convention `<Assignment>_318159506_207283888.{pdf,docx}`.
>
> **Verified from the course briefs (2026-06-19):** the **"Idea Funnel" narrows to one agent by the Week-7
> PRD** (3 ideas → 2 domains → **1 built agent**) — so this PRD covers **Inclusify only**. Demo Day
> presentations: **6 / 13 / 20 July 2026** (+3 / +2 bonus for the top two per batch). Assignment-2 data rule:
> **≤ 50 MB total per domain**, with **≥ 1 RAG-suitable source**. *No separate PRD/Project brief published yet* (team-confirmed) — working spec is
> **Docker + standalone + autonomous**; page-limit / rubric / format are **TBD** pending course release (see §14).

---

## 1. Summary

We are building the **Inclusify Audit Agent**: a standalone, Dockerized **autonomous agent** that audits a
single piece of course material (paper / syllabus / slide text) for non-inclusive language and produces a
**defensible, citation-grounded report**.

The key change from our Assignment-1/2 draft is architectural. The earlier draft was a **fixed pipeline**
(`Extract → Lexicon → LLM → Flag → User review`). By the course's own definition that is *not an agent* — it
"does not make decisions about what to do next." This PRD redesigns the system so that **the system itself
owns the control flow**: it decides, at runtime, which tool to call, how deeply to inspect each span, when to
ground a claim in an authoritative source, when to ask the user a clarifying question, and when to stop.

The same agent has a direct, valuable path into our existing **Inclusify product**: its tools swap from
generic implementations to the product's real endpoints and database, finally delivering the *grounded,
citable* auditing the product was always meant to have but never wired.

---

## 2. Goals & non-goals

> The course's idea funnel reduces to **one** agent at the PRD stage; we build **Inclusify** (idea #1).
> TonePilot (idea #3) is not built — it remains a sibling that shares this exact agent design.

**Goals**
- G1. A genuinely **autonomous** agent (passes the course's Perceive / Reason / **Act Autonomously** test).
- G2. **Standalone**: `docker compose up` and it runs with no dependency on the Inclusify product.
- G3. Maps explicitly to course architectures: **ReAct** (core), **Reflection** (precision), **Agentic-RAG** (grounding).
- G4. Produces a **cited** audit: every surfaced flag is either backed by a real source or explicitly marked *unverified*.
- G5. A clean **integration path** into Inclusify (Seam D + A below).

**Non-goals (this milestone)**
- N1. Multi-document / whole-corpus auditing — documented as the **Supervisor roadmap** (§11), not built now.
- N2. Text *generation* — we audit human-written text; rewrites are suggestions, never autonomous edits.
- N3. Fine-tuning / using the Qwen LoRA in the standalone — detection uses **gpt-5-mini**; the LoRA is an integration-stage tool swap.
- N4. Autonomous writes to any production system — any prod change is gated behind a human.

---

## 3. Why this is an agent and not a pipeline (the grading-critical section)

The course defines the line precisely (Week 5 / Week 6, last lecture):

> **AI Workflow/Pipeline:** "a structured, step-by-step pipeline where data flows through predefined modules…
> the steps are fixed… the system does not make decisions about what to do next. *LLMs may be used inside the
> steps, but the overall flow is still fixed.*"
>
> **AI agent:** "a system designed to **perceive** its environment, **reason** and **autonomously act** to
> achieve specific goals using LLMs." A **ReAct agent** "uses a loop of **Thought → Action → Observation to
> decide what to do next, instead of following a fixed workflow.**"
>
> Slogan: **"Automation != Autonomously."**

Our old draft scored ✅ Perceive / ✅ Reason / ❌ Act Autonomously — identical to the course's canonical
*non*-agent (the "Toby Auto HR" workflow). This design fixes the ❌ with **six runtime decisions the system
makes itself** (a human makes none of them):

| # | Autonomy behavior | The decision the *system* makes | Course mapping |
|---|---|---|---|
| 1 | **Adaptive scrutiny** | Per chunk: cheap lexicon check vs. escalate to deep classification vs. skip | ReAct "decide what to do next" |
| 2 | **Agentic-RAG grounding** | On a weak/ungrounded flag: retrieve from ERIC to confirm; choose the query/source; **retract** if unsupported | Agentic-RAG "decide which source to query" |
| 3 | **Clarifying questions** | On context ambiguity (technical term? quotation? use-mention?): ask the user instead of blindly flagging | ReAct "ask clarifying questions when information is missing" |
| 4 | **Reflection** | Self-critique the finding set before finalizing; drop hallucinations / use-mention false positives | Reflection agent |
| 5 | **Self-owned stop** | Stop when all signal-bearing spans are adjudicated *or* budget is exhausted; report partial if needed | ReAct "Stop" condition |
| 6 | **Tool election** | Choose *which* tool to call each cycle, in an order it picks | ReAct "choose actions / adapt the workflow" |

**Architecture mapping (the "one or more" requirement):** the per-document loop is **ReAct**; the
pre-finalize self-critique is a **Reflection** node; the autonomous "should I ground this, and where?" branch
is **Agentic-RAG**. The multi-document extension (§11) is a **Plan-and-Execute / Supervisor** envelope.

---

## 4. Architecture

```
                         GOAL: "Audit <document> for inclusivity; produce a cited, reviewed report."
                                              │
                                              ▼
   ┌───────────────────────────────  ReAct control loop (LangGraph)  ──────────────────────────────┐
   │                                                                                                 │
   │   PERCEIVE            REASON (gpt-5-mini)                 ACT (elected tool)        OBSERVE      │
   │   ───────             ────────────────────               ─────────────────         ───────      │
   │   doc, language,  →   "what should I do next            →  chunk_document       →   result fed   │
   │   structure,          for this span, given what I       │  lexicon_lookup           back into    │
   │   tool health,        already know?"  (Thought)         │  classify_span            REASON       │
   │   working memory                                        │  retrieve_citation  ◄── Agentic-RAG    │
   │        ▲                      │                          │  propose_rewrite          branch       │
   │        │                      │ chooses among            │  ask_user           ◄── clarifying Q   │
   │        └──────── loop ────────┘ {record│escalate│ground│ │  record_finding                       │
   │                                  ask│skip│reflect│stop}  │                                        │
   │                                                          ▼                                        │
   │                                              (bounded: max iters + token budget)                  │
   └───────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                     │  when stop condition met
                                                     ▼
                                          ┌──────────────────────┐
                                          │  REFLECTION node      │  self-critique the full finding set:
                                          │  (gpt-5-mini)         │  drop hallucinations / use-mention FPs,
                                          └───────────┬──────────┘  dedupe, verify each flag grounded-or-flagged
                                                      ▼
                                          finalize_report()  →  cited audit (JSON + human-readable)
```

**State / memory.** A typed run-state object: the document + chunks, a per-span ledger
(`pending | recorded | retracted | asked`), accumulated findings, a citation cache, and the running
Thought/Action/Observation trace. The ERIC corpus lives in a **Chroma** vector store (semantic memory for
grounding). For a single document, conversational memory is the run-state itself.

**Bounded autonomy (why this won't hurt a precision tool).** The loop is a **LangGraph** state machine with a
hard **max-iteration** and **token budget**; the **Reflection** node is a mandatory quality gate; and **every
decision is logged**. This is the course's own rationale for Plan-and-Execute / Supervisor ("easier
debugging… safer for production") applied to keep the agent auditable.

---

## 5. Tool specifications

| Tool | Input → Output | Backend (standalone) | Notes |
|---|---|---|---|
| `chunk_document` | `text` → `chunks[]` (with char offsets, surrounding context) | local splitter | drops references/bibliography to avoid citation FPs |
| `lexicon_lookup` | `phrase` → `{hit, term, category, canonical_rewrite}` | retext-equality + "Tiny Heap" affixed-words (~0.1 MB, bundled) | the cheap, deterministic first check |
| `classify_span` | `text, context` → `{is_issue, category, severity, confidence, explanation}` | **gpt-5-mini** | clean tool interface so the **Qwen LoRA** can drop in at integration |
| `retrieve_citation` | `phrase, category` → `{source, quote, url, supports: bool}` | **Agentic-RAG** over ERIC (Chroma) | agent chooses to call this; can **retract** an unsupported flag |
| `propose_rewrite` | `span, context` → `{rewrite, preserves_meaning: bool}` | gpt-5-mini | inclusive alternative that keeps technical accuracy |
| `ask_user` | `question, span` → `answer` | dual-mode: **batch** (default — auto-resolve + log assumption) / **interactive** (Demo Day) | for genuine context ambiguity only |
| `record_finding` / `finalize_report` | finding(s) → ledger / final report | local | builds the output in §9 |

---

## 6. Tech stack & packaging

- **Orchestration:** **LangGraph** (LangChain ecosystem — the course-taught stack; LangGraph makes the ReAct
  loop, Reflection node, and stop conditions explicit and inspectable). Classic LangChain `AgentExecutor` is
  the fallback if we want to stay literal to lecture code. **[DECIDED: LangGraph — see §14]**
- **Reasoning + detection model:** **gpt-5-mini** via **Azure OpenAI API**, keys/budget through **LLMod.ai**
  (course portal).
- **Vector store:** **Chroma** (local, CPU) holding the **ERIC corpus** we already have at
  `Assignment 2/academic_inclusivity_corpus.csv` (~42 MB, 21,870 chunks), embedded with
  `text-embedding-3-small` (course embedding model).
- **Packaging:** `docker compose` — services: `ingest` (one-time: load ERIC → Chroma), `chroma`, `agent`
  (FastAPI endpoint + CLI). CPU-only; no GPU. Submit-and-run: `docker compose up` → POST a document or run the
  CLI → cited report.

---

## 7. Data sources (carried from Assignment 2, re-scoped to agent roles)

| Source | Old pipeline role | New agent role |
|---|---|---|
| **ERIC Academic Inclusivity Corpus** (~40 MB, RAG) | fired only by the "Why?" button | **Agentic-RAG tool** the agent *elects* to call to ground/retract a flag |
| **Inclusive-Language Lexicon** (retext-equality + Tiny Heap, ~0.1 MB) | fixed first stage | a **tool**; the agent decides when a cheap lexicon check suffices |
| **SBIC v2** (few-shot exemplars, ~7.2 MB) | injected in every LLM call | **[DECIDED: dropped]** unnecessary with gpt-5-mini; add a few curated implied-bias examples to the `classify_span` prompt only if eval shows weak no-trigger-word recall. **Dropping it keeps the footprint at ~42 MB (ERIC) — comfortably under the 50 MB/domain cap; keeping it pushes to ~49 MB.** |

---

## 8. The decision policy (the agent's "brain")

Expressed as reasoning guidance in the system prompt + LangGraph routing — **heuristics the agent reasons
over, not hard-coded thresholds** (hard thresholds would make it a pipeline again):

- After `lexicon_lookup`: unambiguous known-term hit → `record`; no hit but span carries identity/demographic
  signal → escalate to `classify_span`; clearly neutral → `skip`.
- After `classify_span`: high-confidence + clear category → consider grounding; low-confidence or ambiguous →
  either `retrieve_citation` (confirm/refute) or `ask_user` (if it's a *context* ambiguity: use-mention,
  quotation, technical term).
- `retrieve_citation`: supporting source found → attach citation, keep flag; none found → **retract** or
  mark *unverified* (never surface ungrounded).
- `Reflection`: dedupe; remove use-mention / quotation FPs; confirm each surfaced flag is grounded-or-flagged;
  check rewrites preserve technical meaning.
- `stop`: all signal-bearing spans adjudicated **or** budget hit → `finalize_report`.

The point of autonomy: the agent **chooses among** `{record, escalate, ground, ask, skip, reflect, stop}`
based on observations — there is no fixed order.

---

## 9. Output

A structured report (JSON + rendered):
```json
{
  "document": "syllabus.pdf",
  "summary": { "spans_examined": 142, "flags": 9, "grounded": 7, "unverified": 2, "questions_asked": 1 },
  "findings": [{
    "span": "…", "offset": [1204, 1231], "category": "Generalization", "severity": "Biased",
    "confidence": 0.78, "explanation": "…",
    "citation": { "source": "ERIC #…", "quote": "…", "url": "https://eric.ed.gov/…", "supports": true },
    "suggestion": "…", "status": "grounded"
  }],
  "trace": [ "Thought: … / Action: classify_span / Observation: …", "…" ]
}
```
The `trace` is first-class — it's our **evidence of autonomy** (it shows the *system* choosing each action).

---

## 10. Evaluation plan

**Does it work?** Precision / recall / F1 of flagged spans against a **gold set**: reuse the product's
expert-labeled **Achva data (English portion)** as primary, plus a small (~10–15 span) hand-labeled top-up
for under-covered categories. **[DECIDED]** *(report metrics in the PRD; raw Achva text stays out of any shareable image.)*

**Is it grounded?** % of surfaced flags with a valid supporting citation; # of ungrounded flags **retracted**.

**Is it autonomous? (the differentiator)** Two pieces of evidence:
1. **Decision-trace logs** — the printed Thought → Action → Observation cycles prove the system, not a human, chose each step.
2. **Ablation: agent vs. fixed pipeline** — run the same tools in a fixed order (no agent decisions) as a
   baseline. On documents with use-mention / quoted historical text / technical terms, show the agent **asks /
   grounds / retracts** where the pipeline over-flags — i.e., higher precision *because* of autonomy.

---

## 11. Integration into Inclusify (the product)

**Headline (chosen): Seam D + A.** The *same* agent, with tools swapped to the product's real surfaces:

| Tool | Standalone | Integrated into Inclusify |
|---|---|---|
| `classify_span` | gpt-5-mini | **Qwen2.5-3B LoRA** via `POST /api/v1/analysis/analyze` (vLLM) |
| `retrieve_citation` | Chroma over ERIC | same, **writing real citations into the dead `guideline_sources` / `glossary_terms` tables and `suggestions.source_id`** |
| findings | local report | persisted to `findings` / `suggestions` |
| scrutiny | adaptive | **replaces the fixed per-chunk fan-out** with adaptive, GPU-budget-aware scrutiny |

Why this seam: the shipped product currently has **ungrounded "Why?" explanations** and those citation tables
are **provisioned but unused** — this agent is precisely what activates them. It also turns the blunt global
`[0.30, 0.85]` confidence gate into a per-span, context-aware decision.

**Roadmap (not this milestone):**
- **Multi-document Supervisor envelope** — a Supervisor agent plans a whole syllabus/corpus, dispatches a
  per-document ReAct sub-agent, keeps cross-document memory (don't re-litigate the same phrase; escalate
  systemic patterns), and consolidates one institutional report (Seam A, full form).
- **Feedback-triage agent** (Seam C) and **retraining-loop manager** (Seam B) as later autonomous services.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| ReAct loops / reasoning drift (course-noted con) | hard max-iteration + token budget; LangGraph state machine |
| Non-determinism vs. a precision tool | Reflection quality gate; grounded-or-retract rule; full decision logging |
| LLM-driven policy inconsistency | policy expressed as bounded routing + Reflection; ablation catches regressions |
| Cost / latency | adaptive scrutiny (cheap lexicon first); gpt-5-mini; budget cap |
| Briefs unverified (OneDrive placeholders) | hydrate `course assignments.pdf` + briefs, re-confirm rubric/Docker rule before locking |

---

## 13. Milestones (toward Demo Day — presentations 6 / 13 / 20 July 2026)

- **M0 — this week:** lock this PRD; repo scaffold; ingest ERIC → Chroma; tool interfaces + stubs.
- **M1:** ReAct core loop with real `lexicon_lookup` + `classify_span` + `record_finding`; single-doc end-to-end; decision-trace logging.
- **M2:** `retrieve_citation` (Agentic-RAG) with retract-if-ungrounded; Reflection node; `ask_user` clarifying-question path.
- **M3:** Dockerize (`ingest` + `chroma` + `agent`); CLI/API entrypoint; eval gold set + the pipeline-vs-agent ablation.
- **M4:** Demo Day materials (a trace walkthrough that *shows* the autonomy); the integration design note (Seam D+A wiring + Supervisor roadmap).

---

## 14. Decisions (resolved 2026-06-19)

1. **[DECIDED] Orchestration: LangGraph** (LangChain ecosystem — on-syllabus). Makes the ReAct loop, the Reflection node, the conditional Agentic-RAG branch, the bounded loop, and the per-step decision-trace first-class and auditable — exactly the §10 autonomy evidence. `AgentExecutor` is the fallback only if literal lecture parity is required.
2. **[DECIDED] Gold eval set: reuse the product's Achva expert-labeled data (English portion)** as primary + a small (~10–15 span) hand-labeled top-up for under-covered categories. Its adversarial + benign-baseline docs drive the agent-vs-pipeline ablation. Report metrics in the PRD; keep raw Achva text out of any shareable Docker image.
3. **[DECIDED] Drop SBIC** from the standalone — gpt-5-mini + system prompt + lexicon + Agentic-RAG + Reflection covers implied bias; footprint stays ~42 MB under the 50 MB cap. Escape hatch: add a handful of curated implied-bias exemplars to the `classify_span` prompt only if eval shows weak no-trigger-word recall.
4. **[DECIDED — pending course release] No separate Week-7 PRD / Project brief exists yet** (team-confirmed). Working spec = **Docker + standalone + autonomous** (team requirement); page-limit / rubric / submission format are **TBD** — revisit when the course publishes the brief. Not a blocker; affects final packaging/formatting only.
5. **[DECIDED] `ask_user` dual-mode** — one tool, two resolution policies: **batch** (auto-resolve + log assumption & confidence; default, for reproducible eval/CI) and **interactive** (block for a human; for Demo Day). Logged batch assumptions double as offline autonomy evidence.
```
