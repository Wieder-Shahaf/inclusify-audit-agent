"""Env-driven provider selection round-trips through config.build_*."""
from __future__ import annotations

import os

from inclusify_agent import config


def test_default_llm_is_mock(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert config.build_llm().name == "mock"


def test_default_embeddings_is_hash(monkeypatch) -> None:
    monkeypatch.delenv("EMBEDDINGS_PROVIDER", raising=False)
    impl = config.build_embeddings()
    assert impl.name == "hash"
    assert impl.dim == 64


def test_default_vector_store_is_chroma(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("VECTOR_STORE", raising=False)
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path))
    impl = config.build_vector_store(dim=64)
    assert impl.name == "chroma"


def test_inmemory_selection(monkeypatch) -> None:
    monkeypatch.setenv("VECTOR_STORE", "inmemory")
    impl = config.build_vector_store(dim=32)
    assert impl.name == "inmemory"
    assert impl.dim == 32


def test_openai_compat_llm_selection_needs_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8222/v1")
    monkeypatch.setenv("LLM_MODEL", "gemma-test")
    impl = config.build_llm()
    assert impl.name == "openai_compat"


def test_unknown_provider_raises(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "nonexistent")
    import pytest
    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        config.build_llm()
    os.environ.pop("LLM_PROVIDER", None)
