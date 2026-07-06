"""Embeddings provider interface. Impls: hash / local_st / openai_compat."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsProvider(Protocol):
    """Returns 1-D float vectors for a single string or a list of strings.

    Dim depends on the impl: hash (offline default) picks something cheap; local_st is 384;
    openai_compat (course text-embedding-3-small) is 1536.
    """

    name: str
    dim: int

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        """Return embeddings; accepts a string or list and always returns list-of-vectors."""
        ...
