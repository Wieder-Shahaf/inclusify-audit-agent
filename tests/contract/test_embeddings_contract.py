"""EmbeddingsProvider contract: shape compliance for every impl."""
from __future__ import annotations

from inclusify_agent.providers.embeddings import (
    EmbeddingsProvider,
    HashEmbeddings,
    LocalSTEmbeddings,
    OpenAICompatEmbeddings,
)


def test_hash_satisfies_protocol() -> None:
    impl = HashEmbeddings()
    assert isinstance(impl, EmbeddingsProvider)
    assert impl.name == "hash"
    assert impl.dim == 64


def test_hash_returns_correct_shape_for_str() -> None:
    impl = HashEmbeddings(dim=32)
    out = impl.embed("hello")
    assert len(out) == 1
    assert len(out[0]) == 32
    assert all(isinstance(x, float) for x in out[0])


def test_hash_returns_correct_shape_for_list() -> None:
    impl = HashEmbeddings(dim=32)
    out = impl.embed(["a", "b", "c"])
    assert len(out) == 3
    assert all(len(v) == 32 for v in out)


def test_hash_is_deterministic() -> None:
    a = HashEmbeddings(dim=32).embed("the same text")
    b = HashEmbeddings(dim=32).embed("the same text")
    assert a == b


def test_local_st_class_satisfies_protocol() -> None:
    # Don't load the model (network download); just check the shape.
    assert LocalSTEmbeddings.name == "local_st"
    assert hasattr(LocalSTEmbeddings, "embed")


def test_openai_compat_class_satisfies_protocol() -> None:
    impl = OpenAICompatEmbeddings(base_url="http://localhost")
    assert isinstance(impl, EmbeddingsProvider)
    assert impl.name == "openai_compat"
    assert impl.dim == 1024
