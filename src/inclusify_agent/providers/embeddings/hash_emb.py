"""Deterministic hash-based embedder (zero deps, offline default).

64-dim by default. Same text always yields the same vector — perfect for CI and
contract tests. Quality is poor by design; switch to local_st or openai_compat for
real retrieval.
"""
from __future__ import annotations

import hashlib
import math


class HashEmbeddings:
    name = "hash"

    def __init__(self, dim: int = 64) -> None:
        if dim < 8 or dim > 4096:
            raise ValueError(f"dim {dim} outside reasonable range [8, 4096]")
        self.dim = dim

    def _one(self, text: str) -> list[float]:
        # Stretch sha256 across dim slots; normalize to unit length so cosine works.
        out: list[float] = []
        seed = text.encode("utf-8")
        i = 0
        while len(out) < self.dim:
            h = hashlib.sha256(seed + i.to_bytes(2, "big")).digest()
            for b in h:
                if len(out) >= self.dim:
                    break
                out.append((b - 128) / 128.0)  # roughly [-1, 1)
            i += 1
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        if isinstance(texts, str):
            return [self._one(texts)]
        return [self._one(t) for t in texts]
