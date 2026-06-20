"""Tool: dual-mode clarifying question.

Two modes:
- "auto" (default in offline tests + batch runs): the question is recorded as an event
  in the trace; no input is requested; the finding is marked `asked=True` and kept
  pending. This is the deterministic mode the e2e tests use.
- "interactive" (CLI default for human review): prompts on stdin/stdout.
"""
from __future__ import annotations

import sys
from typing import Any


def ask_user(
    question: str,
    *,
    mode: str = "auto",
    default_answer: str = "unknown",
    stdin: Any = None,
    stdout: Any = None,
) -> dict[str, Any]:
    """Return {"question": str, "answer": str, "mode": "auto"|"interactive"}."""
    if mode not in ("auto", "interactive"):
        raise ValueError(f"ask_user mode must be 'auto' or 'interactive', got {mode!r}")
    if mode == "auto":
        return {"question": question, "answer": default_answer, "mode": "auto"}
    out = stdout or sys.stdout
    inp = stdin or sys.stdin
    print(f"[ask_user] {question}", file=out, flush=True)
    answer = inp.readline().strip() or default_answer
    return {"question": question, "answer": answer, "mode": "interactive"}
