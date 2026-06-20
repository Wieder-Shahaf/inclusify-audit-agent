"""Phase 1 import smoke test (BUILD_PLAN §6, P1 exit check #3).

If any of these imports fail, the pinned dep set in pyproject.toml is broken — fail loud
and fix it before adding more code.
"""


def test_third_party_imports() -> None:
    import chromadb  # noqa: F401
    import langchain  # noqa: F401
    import langgraph  # noqa: F401


def test_inclusify_agent_imports() -> None:
    import inclusify_agent
    from inclusify_agent import config
    from inclusify_agent.providers.embeddings import EmbeddingsProvider
    from inclusify_agent.providers.llm import LLMProvider
    from inclusify_agent.providers.vectorstore import VectorStore

    assert inclusify_agent.__version__
    assert config.DEFAULT_LLM_PROVIDER == "mock"
    assert LLMProvider is not None
    assert EmbeddingsProvider is not None
    assert VectorStore is not None
