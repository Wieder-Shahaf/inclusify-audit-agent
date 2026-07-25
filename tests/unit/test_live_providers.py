"""Offline-safe checks for the keyed providers (OpenAI-compat, Pinecone, Supabase).

No network, no keys: we assert the interface shape, the no-op default, and that
selecting a keyed provider fails loudly (helpful error) rather than silently.
"""
from __future__ import annotations

import importlib.util

import pytest

from inclusify_agent import config
from inclusify_agent.providers.llm.openai_compat import OpenAICompatLLM
from inclusify_agent.providers.persistence import (
    NullPersistence,
    Persistence,
    SupabasePersistence,
)
from inclusify_agent.providers.vectorstore import PineconeStore

_HAS_OPENAI = importlib.util.find_spec("openai") is not None
_HAS_PINECONE = importlib.util.find_spec("pinecone") is not None
_HAS_SUPABASE = importlib.util.find_spec("supabase") is not None


def test_null_persistence_is_noop_and_satisfies_protocol():
    p = NullPersistence()
    assert isinstance(p, Persistence)
    assert p.log_run(prompt="x", status="ok", response="y", steps=[]) is None


def test_build_persistence_defaults_to_null():
    assert config.build_persistence().name == "null"


def test_pinecone_requires_api_key_and_index():
    with pytest.raises(ValueError):
        PineconeStore(api_key="", index="i", dim=8)


def test_supabase_requires_url_and_key():
    with pytest.raises(ValueError):
        SupabasePersistence(url="", key="", table="t")


@pytest.mark.skipif(_HAS_PINECONE, reason="pinecone installed; import-error path not exercised")
def test_pinecone_missing_client_errors_helpfully():
    with pytest.raises(RuntimeError, match="pip install"):
        PineconeStore(api_key="k", index="i", dim=8)


@pytest.mark.skipif(_HAS_SUPABASE, reason="supabase installed; import-error path not exercised")
def test_supabase_missing_client_errors_helpfully():
    with pytest.raises(RuntimeError, match="pip install"):
        SupabasePersistence(url="https://x.supabase.co", key="k")


def test_build_vector_store_pinecone_needs_key(monkeypatch):
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    with pytest.raises(KeyError):
        config.build_vector_store(dim=1536)


def test_openai_compat_requires_config():
    with pytest.raises(ValueError):
        OpenAICompatLLM(base_url="", api_key="", model="")


@pytest.mark.skipif(not _HAS_OPENAI, reason="openai not installed")
def test_openai_compat_client_timeout_is_bounded(monkeypatch):
    """A wedged upstream call must never outlive Vercel's 300 s function cap: the
    client pins an explicit finite timeout + retry budget instead of inheriting
    the SDK defaults (600 s / 2 retries). Client construction is offline."""
    monkeypatch.delenv("LLM_TIMEOUT_S", raising=False)
    llm = OpenAICompatLLM(base_url="https://example.invalid/v1", api_key="k", model="m")
    client = llm._get_client()
    # timeout * (1 + max_retries) must leave room for the error envelope to fire.
    assert float(client.timeout) * (1 + client.max_retries) < 300.0


@pytest.mark.skipif(not _HAS_OPENAI, reason="openai not installed")
def test_openai_compat_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT_S", "90")
    llm = OpenAICompatLLM(base_url="https://example.invalid/v1", api_key="k", model="m")
    assert float(llm._get_client().timeout) == 90.0
