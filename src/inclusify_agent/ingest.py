"""ERIC corpus → vector store. Streaming, offline (no network).

Usage (offline default):
    python -m inclusify_agent.ingest --sample 50 --embedder hash

Reads data/eric/academic_inclusivity_corpus(in).csv row-by-row (the file is ~42MB
so we never load it whole), embeds each chunk's chunk_text, and upserts to the
configured vector store. The default chroma path is .chroma/; pass --store qdrant
to push to Qdrant (uses .env config).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from . import config

_CORPUS_NAME = "academic_inclusivity_corpus(in).csv"


def default_corpus_path() -> Path:
    """Resolve the ERIC corpus path at call time: env -> cwd -> package-relative.

    Called by the CLI to pick up the runtime cwd correctly (the package may live in
    a venv but the corpus is in the repo's data/eric/).
    """
    override = os.environ.get("ERIC_CORPUS_PATH")
    if override:
        return Path(override)
    cwd_candidate = Path.cwd() / "data" / "eric" / _CORPUS_NAME
    if cwd_candidate.exists():
        return cwd_candidate
    return Path(__file__).resolve().parents[2] / "data" / "eric" / _CORPUS_NAME


def stream_rows(corpus_path: Path) -> Iterator[dict[str, str]]:
    """Yield rows from the ERIC CSV one at a time."""
    # csv.field_size_limit needs bumping for long chunk_text fields.
    csv.field_size_limit(2_000_000)
    with open(corpus_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("chunk_text", "").strip():
                yield row


def build_id(row: dict[str, str]) -> str:
    return f"eric_{row.get('chunk_id', '?')}"


def build_metadata(row: dict[str, str]) -> dict[str, Any]:
    return {
        "source": row.get("source", "eric"),
        "doc_id": row.get("doc_id", ""),
        "title": row.get("title", "")[:200],
        "year": row.get("year", ""),
        "url": row.get("url", ""),
    }


def ingest(
    corpus_path: Path,
    *,
    sample: int | None = None,
    batch_size: int = 64,
    embedder: Any = None,
    store: Any = None,
) -> dict[str, Any]:
    """Stream the CSV, embed in batches, upsert. Returns a small summary dict."""
    if not corpus_path.exists():
        raise FileNotFoundError(
            f"ERIC corpus not found at {corpus_path}. "
            "Place academic_inclusivity_corpus(in).csv in data/eric/."
        )
    embedder = embedder or config.build_embeddings()
    store = store or config.build_vector_store(dim=embedder.dim)

    n_total = 0
    n_batches = 0
    batch_ids: list[str] = []
    batch_texts: list[str] = []
    batch_metas: list[dict] = []

    def flush() -> None:
        nonlocal n_batches
        if not batch_ids:
            return
        vectors = embedder.embed(batch_texts)
        store.add(batch_ids, vectors, batch_texts, batch_metas)
        batch_ids.clear()
        batch_texts.clear()
        batch_metas.clear()
        n_batches += 1

    for row in stream_rows(corpus_path):
        if sample is not None and n_total >= sample:
            break
        batch_ids.append(build_id(row))
        batch_texts.append(row["chunk_text"])
        batch_metas.append(build_metadata(row))
        n_total += 1
        if len(batch_ids) >= batch_size:
            flush()
    flush()

    return {
        "corpus": str(corpus_path),
        "ingested": n_total,
        "batches": n_batches,
        "store": store.name,
        "embedder": embedder.name,
        "dim": embedder.dim,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="inclusify_agent.ingest")
    p.add_argument("--corpus", type=Path, default=None)
    p.add_argument("--sample", type=int, default=None,
                   help="Cap row count (offline-default + smoke tests).")
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--embedder", choices=("hash", "local_st", "openai_compat"), default=None,
                   help="Override EMBEDDINGS_PROVIDER env.")
    p.add_argument("--store", choices=("chroma", "inmemory", "qdrant"), default=None,
                   help="Override VECTOR_STORE env.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.embedder:
        os.environ["EMBEDDINGS_PROVIDER"] = args.embedder
    if args.store:
        os.environ["VECTOR_STORE"] = args.store
    corpus = args.corpus or default_corpus_path()
    summary = ingest(corpus, sample=args.sample, batch_size=args.batch_size)
    print(
        f"ingest: {summary['ingested']} rows in {summary['batches']} batches -> "
        f"store={summary['store']} embedder={summary['embedder']} dim={summary['dim']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
