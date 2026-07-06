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
python3.11 -m venv .venv && .venv/bin/pip install ".[dev]"
# Windows: py -3.11 -m venv .venv ; .venv\Scripts\pip install ".[dev]"
.venv/bin/python -m inclusify_agent.cli audit data/fixtures/sample.txt \
    --provider mock --store inmemory
```

Tests + eval (all key-free):

```bash
pytest -q                              # imports + contract + unit + e2e, all offline
python -m eval.run --mock              # control-flow divergence report
python -m inclusify_agent.ingest --sample 50 --embedder hash   # builds .chroma/
```

Grow the ERIC corpus (public api.ies.ed.gov, no key required):

```bash
python scripts/fetch_eric.py --queries data/eric/queries.txt --rows 100
# or one-off:
python scripts/fetch_eric.py --query "inclusive pedagogy" --rows 50
```

Both append to `data/eric/academic_inclusivity_corpus.csv` (gitignored)
with dedup against existing `doc_id`s.

## Run with live providers

One live stack, behind the same interfaces (see [`docs/NEEDS_KEYS.md`](docs/NEEDS_KEYS.md)
for the exact env vars): the **course stack** — LLMod.ai proxy (gpt-5.4-mini +
text-embedding-3-small) + Pinecone + Supabase run logging. **Verified live**; this is
what the Vercel deployment uses. Any other OpenAI-compatible endpoint works the same way.

Swap by editing `.env` (gitignored) — no code change, just re-run ingest if the embedder's
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
  providers/                 # interfaces + impls: llm/ (mock, openai_compat),
                             #   embeddings/ (hash, local_st, openai_compat),
                             #   vectorstore/ (inmemory, chroma, pinecone),
                             #   persistence/ (null, supabase)
  tools/                     # the 9 agent tools (chunk, lexicon_lookup, classify_span,
                             #   retrieve_citation, propose_rewrite, ask_user, record_finding,
                             #   explain_why, eric_live_search)
  graph/                     # LangGraph state machine (perceive/route/act/reflect/stop)
  server/                    # FastAPI app: GUI + /api/* endpoints (+ recording LLM for steps[])
  agent.py / cli.py / report.py / ingest.py
api/index.py                 # Vercel ASGI entrypoint (path is fixed by Vercel)
frontend/                    # web GUI (served by nginx container in docker compose)
data/lexicon/                # see README; lexicon is bundled in src/inclusify_agent/data/
data/fixtures/               # tiny demo input
data/eric/                   # ERIC corpus (gitignored, ~42MB, mounted at runtime)
data/gold/                   # Achva expert review set (gitignored — expert data stays local)
tests/{unit,contract,e2e}/   # all offline; `live`-marked tests are opt-in
eval/                        # gold harness + baseline ablation + Achva classifier eval
scripts/                     # fetch_eric.py, gen_architecture.py
docs/course/                 # submitted course deliverables (slides, project brief)
```

## Versioning + safety

- Branch `dev` (feature work merges back via short-lived `feat/*` branches); per-phase tags
  `p0-bootstrap`…`p7`, milestone tags `v0-offline`, `v1-course-api`.
- No Claude / Anthropic attribution on any commit (CLAUDE.md hard rule #1 + commit-msg hook).
- Destructive teardown of live resources (Pinecone indexes, Supabase tables) is human-only —
  never from an agent session (CLAUDE.md hard rule #6).
