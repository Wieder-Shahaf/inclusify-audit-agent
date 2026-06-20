"""Env-driven provider selection. Offline-first defaults; no API keys required.

Phase 1: placeholder constants only. Phase 2 will wire selection logic.
"""
from __future__ import annotations

import os

DEFAULT_LLM_PROVIDER = "mock"
DEFAULT_EMBEDDINGS_PROVIDER = "hash"
DEFAULT_VECTOR_STORE = "chroma"


def get_llm_provider() -> str:
    return os.environ.get("LLM_PROVIDER", DEFAULT_LLM_PROVIDER)


def get_embeddings_provider() -> str:
    return os.environ.get("EMBEDDINGS_PROVIDER", DEFAULT_EMBEDDINGS_PROVIDER)


def get_vector_store() -> str:
    return os.environ.get("VECTOR_STORE", DEFAULT_VECTOR_STORE)


def get_agent_max_iters() -> int:
    return int(os.environ.get("AGENT_MAX_ITERS", "12"))
