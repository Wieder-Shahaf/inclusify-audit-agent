# Deploying to Vercel

The agent ships as a single FastAPI ASGI app that serves both the GUI (`/`) and the
API (`/api/*`). On Vercel that's one Python serverless function — same-origin, no CORS.

## Files

| File | Role |
|---|---|
| `api/index.py` | ASGI entrypoint — exposes `app`; adds `src/` to the path |
| `vercel.json` | routes every path to the function; `includeFiles` bundles `src/**` + `frontend/**`; `maxDuration` 60s (< the 300s API limit) |
| `requirements.txt` | runtime deps (no chromadb — the deployed API uses the in-memory store) |
| `.vercelignore` | trims the bundle (corpus, tests, docs, venv) to stay under the size cap |

## Deploy

```bash
npm i -g vercel
vercel            # first run links/creates the project
vercel --prod     # production deploy -> https://<project>.vercel.app
```

The GUI is at the root URL; the four endpoints are under `/api/`.

## Environment variables (Vercel → Project → Settings → Environment Variables)

Offline by default (no vars needed). To run the **course live stack**:

| Var | Value |
|---|---|
| `LLM_PROVIDER` | `openai_compat` |
| `LLM_BASE_URL` | LLMod.ai base URL (e.g. `https://api.llmod.ai/v1`) |
| `LLM_API_KEY` | group LLMod.ai key |
| `LLM_MODEL` | `MB5R2CF-azure/gpt-5.4-mini` |
| `EMBEDDINGS_PROVIDER` | `openai_compat` |
| `EMBEDDINGS_BASE_URL` | LLMod.ai base URL |
| `EMBEDDINGS_API_KEY` | group LLMod.ai key |
| `EMBEDDINGS_MODEL` | `MB5R2CF-azure/text-embedding-3-small` |
| `EMBED_DIM` | `1536` |
| `PINECONE_API_KEY` / `PINECONE_INDEX` | Pinecone (if grounding against a Pinecone-ingested corpus) |
| `PERSISTENCE_PROVIDER` / `SUPABASE_URL` / `SUPABASE_KEY` | `supabase` run logging |
| `GROUP_BATCH_ORDER` | `<batch>_<order>` from the presentation list |

## Verify after deploy

```bash
BASE=https://<project>.vercel.app
curl $BASE/api/team_info
curl -X POST $BASE/api/execute -H 'Content-Type: application/json' -d '{"prompt":"The chairman approved it."}'
curl -s -o /dev/null -w '%{content_type}\n' $BASE/api/model_architecture   # image/png
open $BASE/                                                                # GUI
```

**Known check:** the root GUI and the PNG are runtime-opened files, so they rely on
`vercel.json`'s `includeFiles` glob. If the root URL shows the "GUI not bundled"
fallback, confirm `frontend/**` made it into the bundle (or copy `frontend/index.html`
to `src/inclusify_agent/static/index.html`, which `src/**` always includes).

> Per the project plan, the production deploy is performed only after the dev
> environment (`docker compose up`) is verified — see README.
