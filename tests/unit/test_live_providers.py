"""Offline-safe checks for the keyed providers (Pinecone, Supabase).

No network, no keys: we assert the interface shape, the no-op default, and that
selecting a keyed provider fails loudly (helpful error) rather than silently.
"""
from __future__ import annotations

import importlib.util

import pytest

from inclusify_agent import config
from inclusify_agent.providers.persistence import (
    NullPersistence,
    Persistence,
    SupabasePersistence,
)
from inclusify_agent.providers.vectorstore import PineconeStore

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
