"""OpenAI-compatible embeddings (BGE-M3 on work VM, Azure later).

The work-VM BGE-M3 endpoint returns 1024-dim vectors and accepts a list at
/v1/embeddings (no separate batch path needed — verified at smoke time, see
memory/work-vm-live-providers.md).

Uses raw HTTP (requests) not the openai SDK — the endpoint omits the model
metadata the SDK expects.
"""
from __future__ import annotations

from typing import Any


class OpenAICompatEmbeddings:
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "bge-m3",
        dim: int = 1024,
    ) -> None:
        if not base_url:
            raise ValueError("OpenAICompatEmbeddings requires base_url")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self.dim = dim

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        try:
            import requests
        except ImportError as e:
            raise RuntimeError(
                "requests not installed. Install with: pip install '.[live]'"
            ) from e

        payload: dict[str, Any] = {"model": self._model, "input": texts}
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        resp = requests.post(
            f"{self._base_url}/v1/embeddings", json=payload, headers=headers, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [item["embedding"] for item in data]
