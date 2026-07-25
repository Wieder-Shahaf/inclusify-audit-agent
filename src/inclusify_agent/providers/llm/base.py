"""LLM provider interface. Impls: MockLLM (offline default) + OpenAICompatLLM (live)."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """All LLM call-sites go through this interface.

    Implementations must be interchangeable (BUILD_PLAN §3 — contract tests prove this).
    MockLLM is deterministic; OpenAICompatLLM hits any OpenAI-compatible endpoint.
    """

    name: str

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        """Return a completion for a single prompt."""
        ...
