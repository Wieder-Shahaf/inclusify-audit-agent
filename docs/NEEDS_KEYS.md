# Needs-keys checklist

The agent is fully buildable, testable, and runnable **offline with no API keys** —
that's the v0 Definition of Done (BUILD_PLAN §9). The items below depend on credentials
the course will issue (or work-VM endpoints for development); they are implemented
behind provider interfaces and left dormant until keys arrive.

## What's gated on keys

| Capability | Provider impl | Status | Env needed | Verified-by |
|---|---|---|---|---|
| Real LLM (gpt-5-mini) | `AzureOpenAILLM` | **stub** — raises until wired | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` | TBD when course issues keys |
| Live LLM (Gemma 4 on work VM) | `OpenAICompatLLM` | implemented | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | smoke (memory/) |
| Azure embeddings | extend `OpenAICompatEmbeddings` for Azure URL shape | not implemented | `AZURE_EMBEDDINGS_DEPLOYMENT`, `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_API_KEY` | TBD |
| Live embeddings (BGE-M3 on work VM, 1024-dim) | `OpenAICompatEmbeddings` | implemented | `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_API_KEY`, `EMBEDDINGS_MODEL` | smoke |
| Qdrant vector store (work VM) | `QdrantStore` | implemented | `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION` (or `QDRANT_COLLECTION_PREFIX`) | smoke |
| Course LLM + embeddings (gpt-5.4-mini / text-embedding-3-small via LLMod.ai) | `OpenAICompatLLM` + `OpenAICompatEmbeddings` | implemented (OpenAI-compatible proxy) | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL=MB5R2CF-azure/gpt-5.4-mini`; `EMBEDDINGS_*`, `EMBED_DIM=1536` | TBD when LLMod.ai key issued |
| Pinecone vector store (course) | `PineconeStore` | implemented | `PINECONE_API_KEY`, `PINECONE_INDEX`, (`PINECONE_CLOUD`, `PINECONE_REGION`) | TBD when key issued |
| Supabase run logging (course primary DB) | `SupabasePersistence` | implemented | `PERSISTENCE_PROVIDER=supabase`, `SUPABASE_URL`, `SUPABASE_KEY`, (`SUPABASE_TABLE`) | TBD when key issued |
| Real precision/recall metrics | `eval/run.py` against the Achva gold set | scaffold only — synthetic gold | (none new; once LLM is real) | TBD |
| Real agent-vs-baseline ablation numbers | same | scaffold only | (none new) | TBD |

## Switching to live providers (OpenAI-compatible LLM + embedder + Qdrant)

```bash
cp .env.example .env
# Edit .env (gitignored). Fill in your own endpoints — the agent works with any
# OpenAI-compatible LLM endpoint, any OpenAI-shaped embeddings endpoint that
# returns a JSON `data[].embedding` array, and any Qdrant server.
LLM_PROVIDER=openai_compat
LLM_BASE_URL=<your LLM endpoint, e.g. http://host:port/v1>
LLM_API_KEY=<key or 'fake' for unauthenticated endpoints>
LLM_MODEL=<model id served by that endpoint>

EMBEDDINGS_PROVIDER=openai_compat
EMBEDDINGS_BASE_URL=<your embeddings endpoint>
EMBEDDINGS_MODEL=<model id, e.g. bge-m3>
EMBED_DIM=<dim of that model, e.g. 1024>

VECTOR_STORE=qdrant
QDRANT_URL=<your Qdrant URL, e.g. http://host:6333>
QDRANT_COLLECTION=inclusify_eric
QDRANT_COLLECTION_PREFIX=inclusify_

# Re-ingest because the embedder's dim differs from the offline default (64).
docker compose --profile ingest up ingest
docker compose up agent

# Or natively:
python -m inclusify_agent.ingest --sample 500 --embedder openai_compat --store qdrant
python -m inclusify_agent.cli audit data/fixtures/sample.txt
```

## Switching to course Azure (when issued)

```bash
LLM_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<...>
AZURE_OPENAI_DEPLOYMENT=gpt-5-mini

EMBEDDINGS_PROVIDER=azure   # requires extending OpenAICompatEmbeddings for Azure URL shape
AZURE_EMBEDDINGS_DEPLOYMENT=text-embedding-3-small
EMBEDDINGS_BASE_URL=https://<resource>.openai.azure.com
EMBEDDINGS_API_KEY=<...>
EMBED_DIM=1536  # text-embedding-3-small
```

The `AzureOpenAILLM` stub in `src/inclusify_agent/providers/llm/azure.py` raises
`NotImplementedError` — finish it when the deployment name + endpoint are known.

## What does NOT require keys

- `docker compose up agent` — runs the demo audit with MockLLM + hash embedder + inmemory store.
- `pytest -q` — 76 tests, all offline.
- `python -m eval.run --mock` — control-flow divergence report.
- `python -m inclusify_agent.ingest --sample 50 --embedder hash` — populates `.chroma/` with no network.

## Switch-back / teardown

Endpoints and keys live ONLY in `.env` (gitignored). To return to offline-default,
delete `.env` (or run `scripts/teardown_vm.sh --yes` — requires interactive TTY,
see CLAUDE.md hard rule #6). Then `docker compose up` once more for an
offline demo.
