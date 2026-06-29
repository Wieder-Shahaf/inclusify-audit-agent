"""No-op persistence — the offline default. Runs aren't stored anywhere."""
from __future__ import annotations

from typing import Any


class NullPersistence:
    name = "null"

    def log_run(
        self, *, prompt: str, status: str, response: str | None,
        steps: list[dict[str, Any]],
    ) -> None:
        return None
