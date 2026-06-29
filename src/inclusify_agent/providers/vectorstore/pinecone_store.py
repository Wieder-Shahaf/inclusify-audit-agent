"""Pinecone vector store (serverless). The course-specified vector DB.

Same contract as the other stores: add() upserts, search() returns
(id, score, text, metadata). Lazy-imports the pinecone client so the offline
default never pulls it in. Creates the index on first use if absent.

Keys live in .env (gitignored): PINECONE_API_KEY. The index name + dim must match
the embedder (text-embedding-3-small -> 1536).
"""
from __future__ import annotations


class PineconeStore:
    name = "pinecone"

    def __init__(
        self,
        api_key: str,
        index: str,
        dim: int,
        cloud: str = "aws",
        region: str = "us-east-1",
    ) -> None:
        if not api_key or not index:
            raise ValueError("PineconeStore requires api_key and index")
        try:
            from pinecone import Pinecone, ServerlessSpec
        except ImportError as e:
            raise RuntimeError(
                "pinecone not installed. Install with: pip install '.[live]'"
            ) from e
        self.dim = dim
        self._index_name = index
        pc = Pinecone(api_key=api_key)
        existing = {i["name"] for i in pc.list_indexes()}
        if index not in existing:
            pc.create_index(
                name=index, dimension=dim, metric="cosine",
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
        self._index = pc.Index(index)

    def add(
        self,
        ids: list[str],
        vectors: list[list[float]],
        texts: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        if not (len(ids) == len(vectors) == len(texts)):
            raise ValueError("ids, vectors, texts must be same length")
        metas = metadatas or [{} for _ in ids]
        # ponytail: text rides in metadata (Pinecone has no separate text field).
        # Pinecone metadata cap is 40KB/vector; ERIC chunks (<=8k chars) stay well under.
        items = [
            {"id": str(rid), "values": vec, "metadata": {"text": text, **(meta or {})}}
            for rid, vec, text, meta in zip(ids, vectors, texts, metas, strict=True)
        ]
        self._index.upsert(vectors=items)

    def search(
        self, query_vector: list[float], k: int = 5
    ) -> list[tuple[str, float, str, dict]]:
        res = self._index.query(vector=query_vector, top_k=k, include_metadata=True)
        out: list[tuple[str, float, str, dict]] = []
        for m in res.get("matches", []):
            meta = dict(m.get("metadata") or {})
            text = str(meta.pop("text", ""))
            out.append((str(m["id"]), float(m["score"]), text, meta))
        return out
