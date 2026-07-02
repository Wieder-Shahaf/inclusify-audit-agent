# Inclusify Audit Agent

A standalone, autonomous agent that audits academic text for non-inclusive language and produces a
**citation-grounded, self-reviewed** report. It does not just run a fixed pipeline — it decides, per span,
whether to do a cheap lexicon check, escalate to deeper analysis, ground a flag in an authoritative source
(retracting what it can't ground), or ask a clarifying question, then reflects on its findings before
finalizing. ReAct + Reflection + Agentic-RAG, built on LangGraph.

> Design: [`docs/PRD.md`](docs/PRD.md) · Build plan: [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) ·
> Needs-keys: [`docs/NEEDS_KEYS.md`](docs/NEEDS_KEYS.md) · Deploy: [`docs/DEPLOY.md`](docs/DEPLOY.md)

## HTTP API + Web GUI

```bash
docker compose up            # api on :8000, web GUI on http://localhost:3000
```

The GUI (ElevenLabs-style: textarea → **Run audit** → response + full reasoning trace)
is at the root URL. The four endpoints (names fixed by the assignment spec):

| Endpoint | Returns |
|---|---|
| `GET /api/team_info` | team + students |
| `GET /api/agent_info` | description, purpose, prompt_template, prompt_examples |
| `GET /api/model_architecture` | architecture diagram (PNG) |
| `POST /api/execute` | `{prompt}` → `{status, error, response, steps}` — `steps` traces every LLM call (`module`, `prompt.{System_prompt,User_prompt}`, `response`) |

Plus one extra endpoint — the PRD's on-demand "Why?" stage (RAG over the ERIC corpus,
Medium-Article-RAG shape: over-fetch ×5 → dedup by document → strict-grounding prompt
with refusal):

| Endpoint | Returns |
|---|---|
| `POST /api/why` | `{span, category?, reason?}` → `{status, error, explanation, citations, augmented_prompt, steps}` — corpus-grounded explanation of why the span was flagged, with the retrieved passages and the exact augmented prompt |

Run the API alone (no frontend container): `docker compose up api`, or natively
`uvicorn inclusify_agent.server:app`. Deploy to Vercel: see [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Run offline (no API keys)

The default config needs no credentials. Two paths:

### Docker (CLI demo)

```bash
docker compose --profile cli up agent
```

Runs the audit on `data/fixtures/sample.txt` with MockLLM + hash embedder + in-memory store,
emits the JSON report to stdout.

### Native (Python 3.11)

```bash
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install ".[dev]"
.venv/Scripts/python.exe -m inclusify_agent.cli audit data/fixtures/sample.txt \
    --provider mock --store inmemory
```

Tests + eval (all key-free):

```bash
pytest -q                              # 85 tests: imports + contract + unit + e2e
python -m eval.run --mock              # control-flow divergence report
python -m inclusify_agent.ingest --sample 50 --embedder hash   # builds .chroma/
```

Grow the ERIC corpus (public api.ies.ed.gov, no key required):

```bash
python scripts/fetch_eric.py --queries data/eric/queries.txt --rows 100
# or one-off:
python scripts/fetch_eric.py --query "inclusive pedagogy" --rows 50
```

Both append to `data/eric/academic_inclusivity_corpus(in).csv` (gitignored)
with dedup against existing `doc_id`s.

## Run with live providers

Two paths supported behind the same interfaces:

1. **Work-VM (Gemma 4 + BGE-M3 + Qdrant)** — already implemented; flip a few `.env` vars. See
   [`docs/NEEDS_KEYS.md`](docs/NEEDS_KEYS.md) for the exact env.
2. **Course Azure (gpt-5-mini)** — `AzureOpenAILLM` stub is in place; needs the deployment
   wiring when keys are issued.

Both swap by editing `.env` (gitignored) — no code change, just re-run ingest if the embedder's
vector dim changes.

## What you get

- A **JSON report** (schema version 1.0): `version`, `document`, `findings[]`, `stats`, `trace[]`.
- Each finding carries: span, label (`flag`/`ask`/`skip`), category, reason, confidence, suggested
  rewrite, citation, and the `grounded`/`asked`/`retracted` flags the reflection node sets.
- The full **decision trace** is in the report — every routing call, tool execution, and reflection
  decision. The trace event types `ask` and `retract` are the autonomy markers (see `eval/run.py`).
- A **Markdown summary** is one flag away: `--format markdown`.

## Layout

```
src/inclusify_agent/
  providers/                 # LLM, embeddings, vector store interfaces + impls
  tools/                     # the 7 agent tools (chunk, lexicon_lookup, classify_span,
                             #   retrieve_citation, propose_rewrite, ask_user, record_finding)
  graph/                     # LangGraph state machine (perceive/route/act/reflect/stop)
  agent.py / cli.py / report.py / ingest.py
data/lexicon/                # see README; lexicon is bundled in src/inclusify_agent/data/
data/fixtures/               # tiny demo input
data/eric/                   # ERIC corpus (gitignored, ~42MB, mounted at runtime)
tests/{unit,contract,e2e}/   # 76 tests, all offline
eval/                        # gold harness + fixed-pipeline baseline + ablation runner
```

## Versioning + safety

- Branch `dev`; per-phase tags `p1`…`p8`, `v0-offline`.
- No Claude / Anthropic attribution on any commit (CLAUDE.md hard rule #1 + commit-msg hook).
- `scripts/teardown_vm.sh` deletes ONLY the configured Qdrant collection(s) and gitignored local
  stores — requires an interactive TTY + typed confirmation (CLAUDE.md hard rule #6); auto/yolo
  cannot trigger it.
