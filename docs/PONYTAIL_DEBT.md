# Ponytail debt ledger

Deliberate shortcuts and deferrals taken under ponytail mode `full`. Tracking these so
they don't quietly rot into "later means never".

## Open

- **`AzureOpenAILLM` is a stub.** Raises `NotImplementedError` until the course issues
  gpt-5-mini keys. Wiring is straightforward (OpenAI SDK with the Azure endpoint shape) —
  finish in a follow-up phase once keys arrive. (See `src/inclusify_agent/providers/llm/azure.py`.)
- **No Azure-shaped embeddings impl.** `OpenAICompatEmbeddings` works for vLLM-style
  endpoints; Azure has a slightly different URL path (`/openai/deployments/...`). Extend
  the same class with a deployment-aware base_url path when the course Azure embedding
  deployment is known.
- **Synthetic gold set, not Achva.** `eval/gold.py` holds 8 hand-crafted items so the
  ablation harness has shape; the real Achva gold set + numbers ship needs-keys.
- **Lexicon is abridged.** 43 entries in `src/inclusify_agent/data/inclusive_lexicon.json`,
  drawn from retext-equality + Tiny Heap. The full retext-equality set is ~907 categorized
  terms — load via a `--lexicon-path` override or expand the bundled JSON if Phase 5 ingest
  proves we want broader coverage.
- **Reranker (`/rerank/cross-encoder`) not wired.** Available on the work VM; noted in
  memory as YAGNI for v0. Reconsider if the RAG "Why?" path quality is poor under the
  course Azure embeddings.
- **`local_st` embeddings tested as a class only.** `LocalSTEmbeddings` is implemented but
  the contract test doesn't load the model (would need an 80MB sentence-transformers
  download). Add a smoke test under the `live` marker if/when the model is downloaded.
- **MockLLM's `_classify` is a flag-word substring scan.** Fine for the offline demo and
  scripted-trace tests; not for ablation against a real LLM. Real LLM impl supersedes it.

## Closed

- _(none yet — first cycle.)_

## Notes

- The `providers/` interfaces and ≥2 impls each are NOT debt — they're CLAUDE.md hard rule
  #3's keystone, exempt from YAGNI.
- The retract-event reflection node IS load-bearing; do not simplify it away in a future
  ponytail-review.
