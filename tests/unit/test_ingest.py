"""Phase 5 ingest unit test (BUILD_PLAN §6, P5).

Runs against a tiny synthetic CSV (not the 42MB real one) — the contract is the
streaming/batching/embedding pipeline, not the corpus content.
"""
from __future__ import annotations

import gc
from pathlib import Path

from inclusify_agent.ingest import ingest, stream_rows
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.vectorstore import ChromaStore, InMemoryStore
from inclusify_agent.tools import retrieve_citation


def _tiny_corpus(tmp_path: Path) -> Path:
    csv_text = (
        "chunk_id,source,doc_id,title,content_type,chunk_text,subject,year,peerreviewed,url,license\n"
        '1,eric,ED1,Inclusive Language Study,abstract,"Inclusive language fosters belonging.",Inclusion,2020,F,http://e/1,public-domain\n'
        '2,eric,ED2,Gender Neutral Pedagogy,abstract,"Use chairperson instead of chairman in syllabi.",Gender,2021,T,http://e/2,public-domain\n'
        '3,eric,ED3,Workforce Vocabulary,abstract,"Replace manpower with workforce when teaching.",Vocabulary,2022,F,http://e/3,public-domain\n'
        '4,eric,ED4,Empty Row Test,abstract," ",Misc,2023,F,http://e/4,public-domain\n'
    )
    p = tmp_path / "tiny_corpus.csv"
    p.write_text(csv_text, encoding="utf-8")
    return p


def test_stream_rows_skips_empty_chunks(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    rows = list(stream_rows(corpus))
    assert len(rows) == 3  # row 4 has whitespace-only chunk_text → skipped
    assert rows[0]["doc_id"] == "ED1"


def test_ingest_builds_inmemory_store_no_network(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    emb = HashEmbeddings(dim=32)
    store = InMemoryStore(dim=32)
    summary = ingest(corpus, sample=None, batch_size=2, embedder=emb, store=store)
    assert summary["ingested"] == 3
    assert summary["batches"] == 2  # 2 + 1
    # Retrieval works on the populated store.
    cites = retrieve_citation(store, emb, query="chairperson", k=3)
    assert len(cites) >= 1


def test_ingest_sample_cap(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    emb = HashEmbeddings(dim=32)
    store = InMemoryStore(dim=32)
    summary = ingest(corpus, sample=2, batch_size=64, embedder=emb, store=store)
    assert summary["ingested"] == 2


def test_ingest_builds_chroma_store(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path)
    emb = HashEmbeddings(dim=32)
    store_path = tmp_path / "chroma"
    store = ChromaStore(path=str(store_path), collection="ingest_test", dim=32)
    try:
        summary = ingest(corpus, sample=None, batch_size=64, embedder=emb, store=store)
        assert summary["ingested"] == 3
        cites = retrieve_citation(store, emb, query="chairperson", k=3)
        assert len(cites) >= 1
    finally:
        del store
        gc.collect()


def test_ingest_missing_corpus_raises(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(FileNotFoundError, match="ERIC corpus"):
        ingest(tmp_path / "nonexistent.csv")
