# Build & Autonomy Plan — `inclusify-audit-agent` (v0.2)

**Companion to:** `AI_Agent_Technical_PRD_draft.md` (the *what*). This is the *how we build it*: repo
architecture, offline-first provider design, GSD autonomous-loop setup, Opus/Sonnet routing, and a roadmap
with **runnable, key-free exit conditions** so the loop terminates cleanly without a live-LLM quality signal.

**Locked:** repo `inclusify-audit-agent/` (inside the course Project folder) · GSD `new-project → autonomous` (yolo + auto-chain) ·
model split (plan/review → Opus 4.8 max, code → Sonnet medium) · offline-first (no LLM/vector keys) ·
**ponytail** (prompt-only) as the coding-leanness ruleset + per-phase review gate.

---

## 1. Objective & terminal condition

Build the standalone **Inclusify Audit Agent** (ReAct + Reflection + Agentic-RAG, PRD §3–9) as an
independently Dockerized repo, developed by a **GSD autonomous loop**. With **no API keys**, the loop's
terminal condition is the **offline DoD** (§9): everything buildable/testable against **mock/local providers**
is complete and green; anything needing live gpt-5-mini/Azure is implemented behind an interface, left
dormant, and listed in the **needs-keys checklist**.

> GSD executes a roadmap to *completion*; it does not "improve until it plateaus." With no real-LLM quality
> signal, the roadmap DoD **is** the plateau. Every phase below therefore exits on a command that returns 0.

## 2. Repo architecture

```
inclusify-audit-agent/
├── .planning/                 # GSD: PROJECT.md, ROADMAP.md, STATE.md, config.json
├── .claude/
│   ├── agents/                # per-agent model frontmatter (Opus vs Sonnet)
│   ├── skills/                # vendored ponytail*/SKILL.md (prompt-only, pinned commit)
│   └── settings.local.json    # permission allowlist (§5.3) so yolo runs unattended
├── pyproject.toml             # PINNED deps; ruff + pytest config
├── README.md                  # offline run in 1 command + with-keys mode
├── .env.example               # ALL keys optional; offline defaults documented
├── .gitignore                 # data/eric/*, .chroma/, models/, .env, __pycache__
├── .githooks/commit-msg       # strips any Claude/Anthropic author/co-author trailer (§5.6)
├── Dockerfile                 # CPU-only, multi-stage (dev/runtime)
├── docker-compose.yml         # services: ingest (one-shot) · agent   (chroma = embedded, no service)
├── data/
│   ├── lexicon/               # retext-equality + Tiny Heap (bundled ~0.1 MB)
│   ├── fixtures/              # tiny sample docs + seeded citations for offline e2e
│   └── eric/                  # ERIC corpus (gitignored, NOT in image)
├── src/inclusify_agent/
│   ├── config.py              # env-driven provider selection; offline defaults
│   ├── providers/
│   │   ├── llm/               # base.py · mock_llm.py · azure_openai_llm.py
│   │   ├── embeddings/        # base.py · hash.py · local_st.py · azure.py
│   │   └── vectorstore/       # base.py · chroma_store.py · inmemory.py
│   ├── tools/                 # chunk · lexicon_lookup · classify_span · retrieve_citation
│   │   │                      #        · propose_rewrite · ask_user · record_finding
│   ├── graph/                 # LangGraph: state.py · nodes.py · routing.py · reflection.py · build.py
│   ├── agent.py · report.py · ingest.py · cli.py · api.py
├── tests/  unit/ · contract/ · e2e/
└── eval/   gold-set harness + agent-vs-pipeline ablation (structure offline)
```

## 3. Offline-first provider design (keystone)

`config.py` selects each provider from env; **dev defaults need no key**.

| Interface | Dev default (no key) | Prod (key) | Notes |
|---|---|---|---|
| `LLMProvider` | **`MockLLM`** | `AzureOpenAILLM` (gpt-5-mini) | see determinism note ↓ |
| `EmbeddingsProvider` | **`hash`** (tests/CI, fully offline) · `local_st` MiniLM (richer ingest, one-time *download*, no key) | Azure `text-embedding-3-small` | `hash` guarantees no-network runs |
| `VectorStore` | **`Chroma`** embedded (local file) · `inmemory` (tests) | same Chroma | **no hosted DB, no key** |

**`MockLLM` must drive the *whole* graph, not just classification.** It returns deterministic, schema-valid
outputs for **every** LLM call site: `classify_span` (fixed issues for fixture spans), the **reason/route**
node (a scripted tool-choice sequence so the ReAct loop is fully exercised), `reflect` (drops one seeded
false-positive), and `propose_rewrite` (templated). Determinism → reproducible e2e + a **stable decision-trace**
that tests assert on. **Contract tests** (`tests/contract/`) prove `MockLLM`/`AzureOpenAILLM` are interchangeable.

## 4. PRD → phase traceability (nothing dropped)

| PRD element | Built in |
|---|---|
| 7 tools (chunk, lexicon, classify, retrieve_citation, rewrite, ask_user, record) | P3 |
| ReAct loop + tool election + self-owned stop | P4 |
| Reflection node | P4 |
| Agentic-RAG grounding + retract-if-ungrounded | P4 (logic) + P5 (corpus) |
| Clarifying-question (`ask_user` dual-mode) | P3 (tool) + P4 (routing) |
| Adaptive scrutiny (cheap→escalate→skip) | P4 routing |
| Output schema + decision-trace | P6 |
| Eval + agent-vs-pipeline ablation | P7 |
| Docker standalone | P0 skeleton + P8 |

## 5. GSD setup & model routing

**5.1 Bootstrap (P0, done by Opus before the loop):** `mkdir inclusify-audit-agent && git init` (in the course Project folder) →
`git checkout -b dev` → write base files (§2) + seed `.planning/` from the PRD → write `config.json`,
`.claude/agents/*` model frontmatter, `.claude/settings.local.json` → **vendor ponytail prompt-only skills (§5.5)** → **install the git-attribution hook + `CLAUDE.md` rule (§5.6)** →
`git tag p0-bootstrap` → launch `gsd-autonomous` at **standard granularity**.

**5.2 Model routing (custom):**

| Role | Model | Effort |
|---|---|---|
| main session (strategy/decisions, this loop) | **Opus 4.8** | max |
| planner / researcher / plan-check / verifier / code-reviewer | **Opus 4.8** | max where settable |
| **executor (coding)** | **Sonnet** | medium |

Via `gsd-set-profile`/`gsd-settings` + per-agent frontmatter if stock profiles don't split cleanly. **Caveat
(verified at P0):** model is reliably per-agent; *effort* is largely session-level — I'll report the exact
knobs and, worst case, accept a model-only split with the main session at Opus-max.

**5.3 Permission allowlist** (enumerated, scoped to the repo so yolo never stalls):
`Bash(python:* )`, `Bash(python3:*)`, `Bash(pip:*)`, `Bash(pip3:*)`, `Bash(pytest:*)`, `Bash(ruff:*)`,
`Bash(git:*)`, `Bash(docker:*)`, `Bash(docker compose:*)`, `Bash(ls/find/grep/cat/echo/mkdir/wc:*)`,
`Write`/`Edit` under the repo, `Skill(gsd-*)`. **No** prod creds, **no** network-required step at runtime.

**5.4 Runtime specifics:** Python **3.11**; base image `python:3.11-slim`; Chroma persisted to a named Docker
volume mounted into both `ingest` and `agent`; `eval/` is an importable package (`eval/__init__.py`).
Per-phase rollback tags: `p1`, `p2`, …, `v0-offline`.

**5.5 Ponytail integration (prompt-only).** Vendor `skills/ponytail*/SKILL.md` from `DietrichGebert/ponytail`
(MIT, **pinned at commit `0403c4d`**, reviewed 2026-06-19) into `.claude/skills/` — **only the `SKILL.md`
prompt files**. We do **not** install its Node lifecycle hooks, MCP server, statusline, or plugin runtime —
**no third-party code executes in the yolo loop**. Mapping onto the model split: the **Sonnet executor** writes
under the ponytail ladder at mode **`full`** (YAGNI → stdlib → native → dep → one line → minimum; never cuts
validation / security / a11y / tests); the **Opus reviewer** runs **`ponytail-review`** per phase and
**`ponytail-audit`** + **`ponytail-debt`** at P8. Aligns with the PRD's own less-is-more ethos.

**5.6 Git attribution rule (HARD — overrides defaults).** No commit, PR, or push may credit **Claude / Claude
Code / Anthropic** as author or co-author. **Forbidden anywhere in a commit message or PR title/body:** any
`Co-Authored-By: Claude…` trailer, and any `Generated with Claude Code` / `🤖 Generated…` line. Enforced two
ways: (1) the repo **`CLAUDE.md`** states the rule for every executor/reviewer agent; (2) a versioned
**`commit-msg` hook** (`.githooks/commit-msg`, set via `git config core.hooksPath .githooks`) **strips** those
lines automatically — so a slip never reaches history and the loop never stalls. The GSD `ship`/PR step carries
the same rule for PR bodies.

## 6. ROADMAP — phases for `gsd-autonomous` (every exit = a command returning 0)

| Phase | Depends | Deliverable | Exit check (runs offline) |
|---|---|---|---|
| **P0 Bootstrap** | — | repo, branch `dev`, GSD seeded, config/permissions/models set | `git tag p0-bootstrap`; model split confirmed |
| **P1 Scaffold** | P0 | `pyproject` (pinned), ruff/pytest, Dockerfile+compose, README stub, **import smoke** | `ruff check . ` =0; `pytest -q` =0; `python -c "import langgraph,langchain,chromadb"` =0; `docker compose config` =0 |
| **P2 Providers** | P1 | LLM/embeddings/vectorstore interfaces + `MockLLM` + `hash`/`local_st` + Chroma/inmemory | `pytest tests/contract -q` =0 (all impls conform); MockLLM determinism test =0 |
| **P3 Tools** | P2 | all 7 tools + unit tests | `pytest tests/unit -q` =0 |
| **P4 Graph** | P3 | LangGraph state machine + routing + reflection + stop + trace; uses **`inmemory` store seeded from `data/fixtures`** | `pytest tests/e2e -q` =0: audit of fixture yields ≥1 finding, ≥1 *retracted/asked* span, non-empty trace |
| **P5 Ingest** | P2 | ERIC→Chroma + `--sample N`; embedder `hash` (gate, offline) / `local_st` (optional, one-time download) | `python -m inclusify_agent.ingest --sample 50 --embedder hash` builds a store; `retrieve_citation` returns ≥1 hit (test) =0 — **no network** |
| **P6 Report + entrypoints** | P4,P5 | output schema + renderer + CLI (+API) | `python -m inclusify_agent.cli audit data/fixtures/sample.txt --provider mock` emits valid JSON (schema-checked) with findings + trace; exit 0 |
| **P7 Eval/ablation** | P6 | gold-set harness (structure) + agent-vs-pipeline ablation | `python -m eval.run --mock` =0 and prints **control-flow divergence** — the agent emits `ask`/`retract` trace events where the fixed-order baseline does not. Proves *capability*, not quality; real metrics are needs-keys (§9). |
| **P8 Package** | P6,P7 | end-to-end Docker, offline demo, README, **needs-keys checklist**, **`ponytail-audit` + `ponytail-debt` ledger** | `docker compose up` runs a demo audit on a fixture and writes a report; `ponytail-audit` prints `net: -N lines/-M deps`; `ponytail-debt` ledger written; `git tag v0-offline` |

**Per-phase leanness gate:** after a coding phase's tests go green and before it closes, the Opus reviewer runs
**`ponytail-review`** on the phase diff and the executor applies the delete-list — folded into the phase's
`code-reviewer` gate, so over-engineering can block phase closure just like a failing test.

## 7. Testing strategy

unit (tools/providers) · contract (provider conformance — same suite for mock & real) · e2e (full offline
audit). **All green with zero keys** is the bar GSD's `verifier`/`nyquist` gates enforce per phase. Optional
GitHub Actions CI runs the same, key-free (uses `hash` embedder for no-network).

**Anti-tautology:** e2e/contract tests assert **structural invariants** — valid output schema; the trace
contains an `ask` and a `retract` event; ≥1 *grounded* finding; the loop stops within `max_iters` — **not** the
exact `MockLLM` strings, so a test can't pass merely because the same executor authored both the mock and the
assertion. The Opus `code-reviewer`/`verifier` owns the *intent* of these invariants.

## 8. Risks & guardrails (yolo autonomous coding)

| Risk | Concrete guardrail |
|---|---|
| Destructive command | allowlist scoped to repo (§5.3); no prod creds present; work on branch `dev`, never `main` |
| Unrecoverable bad state | **atomic commit + `git tag` per phase** → `git reset --hard <tag>` rolls back any phase |
| Sonnet coding drift / **over-building** | Opus `plan-check`+`verifier`+`code-reviewer` gates; **ponytail ladder always-on for the executor** + per-phase **`ponytail-review`**; phase can't close until its exit check returns 0 |
| **Phase fails repeatedly** | policy: executor retries ≤2; still failing → **pause and checkpoint to human** (even under yolo) instead of thrashing |
| Loop spins w/o quality signal | runnable per-phase exits (§6) + global offline DoD (§9) |
| Secret hygiene | `.env` gitignored; only `.env.example`; no keys exist yet; CI key-free |
| Cost runaway | bulk coding on Sonnet; cap loop at the 8 phases; Opus only on plan/review/verify |
| Version churn (LangGraph/LangChain/Chroma) | **pin versions** in `pyproject`; P1 import-smoke catches breakage immediately |
| `local_st` needs a download | `hash` embedder is the no-network default for tests/CI; `local_st` only for richer local ingest |
| ERIC bloats repo/image | gitignored, streamed at ingest, excluded from image; only a fixture is bundled |
| **Vacuous/tautological tests** (executor writes the mock *and* its assertions) | tests assert structural invariants, not mock literals (§7); Opus reviewer owns invariant intent; ablation checks *trace events*, not mock values |
| **Third-party skill supply chain** (ponytail) | **vendor prompt-only** `SKILL.md`; **no** Node hooks / MCP / plugin runtime executed in the loop; pinned at reviewed commit `0403c4d` (MIT) |
| **Ponytail over-deletes load-bearing structure** | always-on mode **`full`** (not `ultra`); **provider interfaces are exempt** (each has ≥2 impls + are the offline-first keystone → they pass YAGNI); ponytail never cuts tests/validation/security by design |
| **Claude attribution leaks into git** | repo `CLAUDE.md` rule + versioned `commit-msg` hook auto-strips any `Co-Authored-By: Claude…` / `Generated with Claude Code` line (§5.6); covers commits, PRs, pushes |

## 9. Definition of Done (offline) + needs-keys checklist

**Done (loop stops):** P0–P8 complete; `pytest -q` (unit+contract+e2e) =0 with **no keys**; `docker compose up`
runs a demo audit on a fixture (MockLLM + `hash`/`local_st`); README documents offline + with-keys modes;
decision-trace renders; `git tag v0-offline` exists.

**Deferred (documented, non-blocking):** swap `MockLLM`→`AzureOpenAILLM` (gpt-5-mini) and `hash/local`→Azure
embeddings; real precision/recall on the Achva gold set; real ablation numbers; (integration track) point
`classify_span` at the Qwen LoRA endpoint and write citations into `guideline_sources`/`suggestions`.

## 10. Checkpoints to the human (me/you)

The loop surfaces a checkpoint at: P0 (model-split confirmation), any phase that fails its exit check twice,
and P8 (final offline DoD + needs-keys handoff). Otherwise it runs P1→P8 unattended.
