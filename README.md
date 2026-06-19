# Inclusify Audit Agent

A standalone, autonomous agent that audits academic text for non-inclusive language and produces a
**citation-grounded, self-reviewed** report. It does not just run a fixed pipeline — it decides, per span,
whether to do a cheap lexicon check, escalate to deeper analysis, ground a flag in an authoritative source
(retracting what it can't ground), or ask a clarifying question, then reflects on its findings before
finalizing. ReAct + Reflection + Agentic-RAG, built on LangGraph.

> Design: [`docs/PRD.md`](docs/PRD.md) · Build plan: [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md)

## Run offline (no API keys)

```bash
docker compose up        # builds the corpus + runs a demo audit on a bundled fixture
```

Or locally: `pytest -q` (unit + contract + e2e, all key-free).

## Modes

Defaults are fully offline: a deterministic `MockLLM`, a `hash` embedder, and a local Chroma store. Set real
providers in `.env` (see `.env.example`) to switch to gpt-5-mini + Azure embeddings.
