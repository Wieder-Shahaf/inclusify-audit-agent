"""OpenAI-compatible LLM (any OpenAI-shaped endpoint; used with the course LLMod.ai proxy).

Only base_url + api_key + model change between endpoints. Lazy-imports the openai SDK so
the offline default never pulls it in.

The base_url and api_key live in .env (gitignored). Trace/log records the provider
NAME ("openai_compat"), never the URL — leave-no-evidence discipline.
"""
from __future__ import annotations

from typing import Any


class OpenAICompatLLM:
    name = "openai_compat"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        if not base_url or not api_key or not model:
            raise ValueError("OpenAICompatLLM requires base_url, api_key, and model")
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy
        self.usage_in = 0
        self.usage_out = 0

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as e:
                raise RuntimeError(
                    "openai package not installed. Install with: pip install '.[live]'"
                ) from e
            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    def complete(self, prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        client = self._get_client()
        # Only send temperature when a caller asks for it: gpt-5.x endpoints
        # (LLMod.ai/LiteLLM) reject any value other than the server default.
        extra: dict[str, Any] = {}
        if "temperature" in kwargs:
            extra["temperature"] = kwargs["temperature"]
        resp = client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 512),
            **extra,
        )
        usage = getattr(resp, "usage", None)  # some OpenAI-compat providers omit it
        if usage is not None:
            self.usage_in += getattr(usage, "prompt_tokens", 0) or 0
            self.usage_out += getattr(usage, "completion_tokens", 0) or 0
        return resp.choices[0].message.content or ""

    def usage(self) -> dict[str, int]:
        """Cumulative token usage across every `complete()` call on this instance
        (course req #1c: a visible budget). A fresh provider per request (see
        `server/app.py::execute_prompt`) makes this per-request, not process-lifetime."""
        return {"in": self.usage_in, "out": self.usage_out}
