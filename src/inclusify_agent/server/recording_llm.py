"""Recording decorator around any LLMProvider.

Every LLM call in the graph goes through `llm.complete(prompt, system=..., task=...)`.
Wrapping the provider lets us capture the assignment-required `steps` trace
(one entry per LLM call) without touching a single tool or node.

MODULE_BY_TASK is the SINGLE SOURCE OF TRUTH for sub-module names — the same names
must appear in the architecture diagram (scripts/gen_architecture.py) and in the
`steps[].module` field (assignment §C: names must be consistent across all three).
"""
from __future__ import annotations

import json
from typing import Any

# task kwarg (set at each call-site) -> architecture sub-module name.
MODULE_BY_TASK = {
    "route": "Router",
    "classify": "SpanClassifier",
    "rewrite": "RewriteComposer",
    "reflect": "Reflector",
    "ground": "GroundingChecker",
}


def _as_obj(raw: str) -> Any:
    """The agent's LLM responses are JSON strings; return parsed object when possible."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


class RecordingLLM:
    """Wraps an LLMProvider; appends one step dict per call to `self.steps`."""

    def __init__(self, inner: Any, steps: list[dict[str, Any]]) -> None:
        self.inner = inner
        self.steps = steps
        self.name = getattr(inner, "name", "llm")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
        response = self.inner.complete(prompt, system=system, **kwargs)
        self.steps.append({
            "module": MODULE_BY_TASK.get(kwargs.get("task", ""), "Agent"),
            "prompt": {"System_prompt": system or "", "User_prompt": prompt},
            "response": _as_obj(response),
        })
        return response


if __name__ == "__main__":
    # ponytail: smallest check that the wrapper records what it should.
    class _Echo:
        name = "echo"
        def complete(self, prompt, *, system=None, **kw):  # noqa: ANN001
            return json.dumps({"ok": True})

    steps: list[dict] = []
    RecordingLLM(_Echo(), steps).complete("hi", system="sys", task="classify")
    assert steps[0]["module"] == "SpanClassifier"
    assert steps[0]["prompt"] == {"System_prompt": "sys", "User_prompt": "hi"}
    assert steps[0]["response"] == {"ok": True}
    print("recording_llm self-check ok")
