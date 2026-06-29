"""Persistence interface: log one audit run. Supabase is the course primary DB.

Kept deliberately tiny — the API is stateless, so persistence is opt-in run logging
(history / analytics), never on the request's critical path.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Persistence(Protocol):
    name: str

    def log_run(
        self, *, prompt: str, status: str, response: str | None,
        steps: list[dict[str, Any]],
    ) -> None:
        """Persist one /api/execute call. Must never raise into the request path."""
        ...
