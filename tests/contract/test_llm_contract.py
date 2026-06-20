"""LLM contract: every impl must satisfy LLMProvider's shape.

BUILD_PLAN §3 — MockLLM, OpenAICompatLLM, and AzureOpenAILLM must be interchangeable.
We don't hit the live endpoints here (offline-first); we just assert each class has
the protocol's name attribute and a callable complete(). Live behavior is checked by
the 'live' marker (opt-in).
"""
from __future__ import annotations

from inclusify_agent.providers.llm import (
    AzureOpenAILLM,
    LLMProvider,
    MockLLM,
    OpenAICompatLLM,
)


def test_mock_satisfies_protocol() -> None:
    impl = MockLLM()
    assert isinstance(impl, LLMProvider)
    assert impl.name == "mock"


def test_openai_compat_satisfies_protocol() -> None:
    # Instantiation needs URL/key/model; we use throwaway values — the SDK is lazy.
    impl = OpenAICompatLLM(base_url="http://localhost", api_key="x", model="x")
    assert isinstance(impl, LLMProvider)
    assert impl.name == "openai_compat"


def test_azure_stub_satisfies_protocol_class() -> None:
    # Stub raises on instantiation without keys. The class itself is the surface.
    assert AzureOpenAILLM.name == "azure"
    assert hasattr(AzureOpenAILLM, "complete")


def test_mock_complete_returns_string_for_every_task() -> None:
    impl = MockLLM()
    for task in ("classify", "route", "reflect", "rewrite", "ground", ""):
        out = impl.complete("anything", task=task)
        assert isinstance(out, str)
        assert len(out) > 0
