"""sentence-transformers embedder (one-time model download, no API key).

Lazy import. Default model: all-MiniLM-L6-v2 (384-dim, ~80MB).
"""
from __future__ import annotations

from typing import Any


class LocalSTEmbeddings:
    name = "local_st"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None
        self.dim = 384  # MiniLM-L6-v2; corrected after lazy load if a different model is used.

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as e:
                raise RuntimeError(
                    "sentence-transformers not installed. Install with: pip install '.[local-st]'"
                ) from e
            self._model = SentenceTransformer(self._model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        model = self._get_model()
        vectors = model.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]
