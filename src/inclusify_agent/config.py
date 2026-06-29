"""Env-driven provider selection. Offline-first defaults; no API keys required."""
from __future__ import annotations

import os
from typing import Any

DEFAULT_LLM_PROVIDER = "mock"
DEFAULT_EMBEDDINGS_PROVIDER = "hash"
DEFAULT_VECTOR_STORE = "chroma"


def get_llm_provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)


def get_embeddings_provider_name() -> str:
    return os.environ.get("EMBEDDINGS_PROVIDER", DEFAULT_EMBEDDINGS_PROVIDER)


def get_vector_store_name() -> str:
    return os.environ.get("VECTOR_STORE", DEFAULT_VECTOR_STORE)


def get_agent_max_iters() -> int:
    return int(os.environ.get("AGENT_MAX_ITERS", "12"))


def build_llm() -> Any:
    name = get_llm_provider_name()
    if name == "mock":
        from .providers.llm import MockLLM
        return MockLLM()
    if name == "openai_compat":
        from .providers.llm import OpenAICompatLLM
        return OpenAICompatLLM(
            base_url=os.environ["LLM_BASE_URL"],
            api_key=os.environ.get("LLM_API_KEY", "fake"),
            model=os.environ["LLM_MODEL"],
        )
    if name == "azure":
        from .providers.llm import AzureOpenAILLM
        return AzureOpenAILLM(
            endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5-mini"),
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {name!r}")


def build_embeddings() -> Any:
    name = get_embeddings_provider_name()
    if name == "hash":
        from .providers.embeddings import HashEmbeddings
        return HashEmbeddings(dim=int(os.environ.get("EMBED_DIM", "64")))
    if name == "local_st":
        from .providers.embeddings import LocalSTEmbeddings
        return LocalSTEmbeddings(model_name=os.environ.get("EMBEDDINGS_MODEL", "all-MiniLM-L6-v2"))
    if name == "openai_compat":
        from .providers.embeddings import OpenAICompatEmbeddings
        return OpenAICompatEmbeddings(
            base_url=os.environ["EMBEDDINGS_BASE_URL"],
            api_key=os.environ.get("EMBEDDINGS_API_KEY", ""),
            model=os.environ.get("EMBEDDINGS_MODEL", "bge-m3"),
            dim=int(os.environ.get("EMBED_DIM", "1024")),
        )
    raise ValueError(f"Unknown EMBEDDINGS_PROVIDER: {name!r}")


def build_vector_store(dim: int) -> Any:
    name = get_vector_store_name()
    if name == "chroma":
        from .providers.vectorstore import ChromaStore
        return ChromaStore(
            path=os.environ.get("CHROMA_PATH", ".chroma"),
            collection=os.environ.get("QDRANT_COLLECTION", "inclusify_eric"),
            dim=dim,
        )
    if name == "inmemory":
        from .providers.vectorstore import InMemoryStore
        return InMemoryStore(dim=dim)
    if name == "qdrant":
        from .providers.vectorstore import QdrantStore
        return QdrantStore(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ.get("QDRANT_API_KEY", ""),
            collection=os.environ.get("QDRANT_COLLECTION", "inclusify_eric"),
            dim=dim,
        )
    if name == "pinecone":
        from .providers.vectorstore import PineconeStore
        return PineconeStore(
            api_key=os.environ["PINECONE_API_KEY"],
            index=os.environ.get("PINECONE_INDEX", "inclusify-eric"),
            dim=dim,
            cloud=os.environ.get("PINECONE_CLOUD", "aws"),
            region=os.environ.get("PINECONE_REGION", "us-east-1"),
        )
    raise ValueError(f"Unknown VECTOR_STORE: {name!r}")


def get_persistence_provider_name() -> str:
    return os.environ.get("PERSISTENCE_PROVIDER", "null")


def build_persistence() -> Any:
    """Run-log sink. Defaults to a no-op so the offline app needs no database."""
    name = get_persistence_provider_name()
    if name == "null":
        from .providers.persistence import NullPersistence
        return NullPersistence()
    if name == "supabase":
        from .providers.persistence import SupabasePersistence
        return SupabasePersistence(
            url=os.environ["SUPABASE_URL"],
            key=os.environ["SUPABASE_KEY"],
            table=os.environ.get("SUPABASE_TABLE", "audit_runs"),
        )
    raise ValueError(f"Unknown PERSISTENCE_PROVIDER: {name!r}")
