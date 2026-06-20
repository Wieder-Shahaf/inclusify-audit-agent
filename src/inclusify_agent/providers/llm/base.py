"""LLM provider interface. Phase 2 wires MockLLM + OpenAICompatLLM + AzureOpenAILLM stub."""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """All LLM call-sites in the graph go through this interface.

    Implementations must be interchangeable (BUILD_PLAN §3 — contract tests prove this).
    MockLLM is deterministic; OpenAICompatLLM hits vLLM/Azure-compatible endpoints; the
    Azure stub is reserved for the course's gpt-5-mini swap.
    """

    name: str

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:
        """Return a completion for a single prompt."""
        ...
