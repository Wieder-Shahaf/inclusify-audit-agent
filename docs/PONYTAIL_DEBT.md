# Ponytail debt ledger

Deliberate shortcuts and deferrals taken under ponytail mode `full`. Tracking these so
they don't quietly rot into "later means never".

## Open

- **Lexicon is abridged.** 43 entries in `src/inclusify_agent/data/inclusive_lexicon.json`,
  drawn from retext-equality + Tiny Heap. The full retext-equality set is ~907 categorized
  terms — load via a `--lexicon-path` override or expand the bundled JSON if Phase 5 ingest
  proves we want broader coverage.
- **`local_st` embeddings tested as a class only.** `LocalSTEmbeddings` is implemented but
  the contract test doesn't load the model (would need an 80MB sentence-transformers
  download). Add a smoke test under the `live` marker if/when the model is downloaded.
- **MockLLM's `_classify` is a flag-word substring scan.** Fine for the offline demo and
  scripted-trace tests; not for ablation against a real LLM. Real LLM impl supersedes it.

## Closed

- **Work-VM + Azure POC stacks removed.** `AzureOpenAILLM` (never left stub),
  `QdrantStore`, `scripts/teardown_vm.sh`, and the Gemma/BGE-M3 wiring are deleted —
  the verified LLMod.ai course proxy + Pinecone superseded both POC paths, and the
  work-VM reranker idea went with them (2026-07-06).
- **Synthetic gold set, not Achva.** `eval/achva.py` now measures classify_span agreement
  against the expert review set in `data/gold/achva/` (gitignored — expert data stays
  local; the script is committed, the data is not). `eval/gold.py`'s 8 synthetic items
  remain only as the offline ablation-harness shape (2026-07-06).
- **`qdrant-client` version pin.** Server is 1.8.1; pinned client to `1.8.2` in
  `[live]` extras (2026-06-20).
- **Live LLMs returned prose, not JSON.** Added explicit JSON-only system prompts to
  `classify_span` and `propose_rewrite` + `_json_extract.py` helper for fenced/prose-
  wrapped output. Live audit now produces valid findings (2026-06-20).
- **Lexicon hints not surfaced to the LLM at rewrite time.** Now passed through —
  lexicon hits become rewrite instructions ("blacklist" → "denylist") instead of
  Gemma inventing its own (2026-06-20).

## Notes

- The `providers/` interfaces and ≥2 impls each are NOT debt — they're CLAUDE.md hard rule
  #3's keystone, exempt from YAGNI.
- The retract-event reflection node IS load-bearing; do not simplify it away in a future
  ponytail-review.
