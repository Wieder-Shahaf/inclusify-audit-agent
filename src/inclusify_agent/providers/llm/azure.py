"""Azure OpenAI LLM stub. Wired when the course issues gpt-5-mini keys.

Until then it raises on instantiation so accidental selection fails loudly rather than
silently falling back to mock.
"""
from __future__ import annotations

from typing import Any


class AzureOpenAILLM:
    name = "azure"

    def __init__(
        self,
        endpoint: str = "",
        api_key: str = "",
        deployment: str = "gpt-5-mini",
    ) -> None:
        if not endpoint or not api_key:
            raise NotImplementedError(
                "AzureOpenAILLM stub: set AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY "
                "(and AZURE_OPENAI_DEPLOYMENT) in .env before selecting LLM_PROVIDER=azure. "
                "Implementation lands when course keys are issued."
            )
        self._endpoint = endpoint
        self._api_key = api_key
        self._deployment = deployment

    def complete(self, prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
        raise NotImplementedError("AzureOpenAILLM not implemented; using stub.")
