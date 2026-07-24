# Needs-keys checklist

The agent is fully buildable, testable, and runnable **offline with no API keys** —
that's the v0 Definition of Done (BUILD_PLAN §9). The items below depend on the
course-issued credentials; they are implemented behind provider interfaces and stay
dormant until the env vars are set.

## What's gated on keys

| Capability | Provider impl | Status | Env needed | Verified-by |
|---|---|---|---|---|
| Course LLM + embeddings (gpt-5.4-mini / text-embedding-3-small via LLMod.ai) | `OpenAICompatLLM` + `OpenAICompatEmbeddings` | **verified live** — note: `LLM_BASE_URL` includes `/v1`, `EMBEDDINGS_BASE_URL` must NOT (provider appends `/v1/embeddings`); gpt-5.x rejects non-default `temperature` (provider omits it) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL=MB5R2CF-azure/gpt-5.4-mini`; `EMBEDDINGS_*`, `EMBED_DIM=1536` | live e2e via `/api/execute` |
| Pinecone vector store (course) | `PineconeStore` | **verified live** — index `inclusify-eric` (1536, cosine, serverless aws/us-east-1) auto-created; ERIC corpus ingested | `PINECONE_API_KEY`, `PINECONE_INDEX`, (`PINECONE_CLOUD`, `PINECONE_REGION`) | live ingest + `/api/execute` citation |
| Supabase run logging (course primary DB) | `SupabasePersistence` | **verified to DB edge** — client OK (supabase ≥2.31 needed for `sb_publishable_` keys); `audit_runs` table created; insert blocked until an RLS policy is added (see `supabase_store.py` docstring); `tokens_in`/`tokens_out` columns (R7 budget ledger) are optional and only populated when the LLM provider exposes `usage()` | `PERSISTENCE_PROVIDER=supabase`, `SUPABASE_URL`, `SUPABASE_KEY`, (`SUPABASE_TABLE`) | pending RLS policy decision |
| Real span-level P/R/F1 on the gold paper | `eval/run.py --gold doc` (v2 `run_v2` end to end) | harness measures the v2 pipeline (span P/R/F1, FP-on-correct, wall-clock, LLM calls); needs a live-provider run + the gitignored `data/gold/achva/doc_gold.json` | `LLM_*`/`EMBEDDINGS_*` (as above) | TBD — README "Metrics" table |
| Real sentence-level Auditor accuracy | `eval/run.py --gold achva-en` (v2 `audit_document`) | harness measures the v2 DocumentAuditor's flag/skip judgment per Achva sentence; `eval/achva.py` (the older `classify_span`-only measurement) stays as the ablation reference | `LLM_*` (as above) | TBD — README "Metrics" table |

## Switching to the live course stack

```bash
cp .env.example .env
# Edit .env (gitignored): uncomment the "Course live stack" block and fill in the
# group key. The agent works with any OpenAI-compatible LLM endpoint and any
# OpenAI-shaped embeddings endpoint that returns a JSON `data[].embedding` array.

# Re-ingest because the embedder's dim differs from the offline default (64):
python -m inclusify_agent.ingest --embedder openai_compat --store pinecone
python -m inclusify_agent.cli audit data/fixtures/sample.txt
```

## What does NOT require keys

- `docker compose up` — API + GUI with MockLLM + hash embedder + inmemory store.
- `pytest -q` — full suite, all offline.
- `python -m eval.run --mock` — control-flow divergence report (v2 pipeline, synthetic gold).
- `python -m eval.run --mock --gold doc --gold-path <p>` — v2 pipeline (`run_v2`) end to end on any
  local `doc_gold.json`; metrics are plumbing-only in mock mode, but the wiring is fully offline.
- `python -m inclusify_agent.ingest --sample 50 --embedder hash` — populates `.chroma/` with no network.

## Switch-back

Endpoints and keys live ONLY in `.env` (gitignored). To return to offline-default,
delete `.env`, then `docker compose up` once more for an offline demo.
