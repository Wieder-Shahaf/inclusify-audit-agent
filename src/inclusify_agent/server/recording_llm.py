"""Recording decorator around any LLMProvider.

Every LLM call in the v2 pipeline goes through `llm.complete(prompt, system=...,
task=...)`. Wrapping the provider lets us capture the assignment-required `steps`
trace (one entry per LLM call) without touching a single tool or node.

MODULE_BY_TASK is the SINGLE SOURCE OF TRUTH for sub-module names — the same three
names must appear in the architecture diagram (scripts/gen_architecture.py) and in
`GET /api/agent_info`'s description (assignment §C: names must be consistent across
all three). v1's task names (route/classify/rewrite/reflect/ground) are gone: the v2
server (server/app.py) only ever calls `run_v2`/`investigate`, which only ever tag
calls "audit"/"investigate"/"consolidate".
"""
from __future__ import annotations

import json
from typing import Any

# task kwarg (set at each call-site) -> architecture sub-module name.
MODULE_BY_TASK = {
    "audit": "DocumentAuditor",
    "investigate": "EvidenceInvestigator",
    "consolidate": "ReportConsolidator",
}


def _as_obj(raw: str) -> Any:
    """The agent's LLM responses are JSON strings; return parsed object when possible.

    A model occasionally emits several JSON objects back-to-back in one completion;
    parse that as a list so steps[].response stays structured (the spec's step sketch
    shows an object, not a string). Any non-JSON tail keeps the raw text untouched —
    the trace must stay faithful to what the model actually said."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        if not isinstance(raw, str):
            return raw
    decoder = json.JSONDecoder()
    values: list[Any] = []
    idx, n = 0, len(raw)
    while True:
        while idx < n and raw[idx].isspace():
            idx += 1
        if idx >= n:
            break
        try:
            value, idx = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            return raw
        values.append(value)
    # A single value would have parsed above; only a true sequence lands here.
    return values if len(values) > 1 else raw


class RecordingLLM:
    """Wraps an LLMProvider; appends one step dict per call to `self.steps`."""

    def __init__(self, inner: Any, steps: list[dict[str, Any]]) -> None:
        self.inner = inner
        self.steps = steps
        self.name = getattr(inner, "name", "llm")

    def complete(self, prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
        usage_fn = getattr(self.inner, "usage", None)
        before = usage_fn() if callable(usage_fn) else None
        response = self.inner.complete(prompt, system=system, **kwargs)
        step: dict[str, Any] = {
            "module": MODULE_BY_TASK.get(kwargs.get("task", ""), "Agent"),
            "prompt": {"System_prompt": system or "", "User_prompt": prompt},
            "response": _as_obj(response),
        }
        if before is not None:
            after = usage_fn()
            step["usage"] = {"in": after["in"] - before["in"], "out": after["out"] - before["out"]}
        self.steps.append(step)
        return response


if __name__ == "__main__":
    # ponytail: smallest check that the wrapper records what it should.
    class _Echo:
        name = "echo"
        def complete(self, prompt, *, system=None, **kw):  # noqa: ANN001
            return json.dumps({"ok": True})

    steps: list[dict] = []
    RecordingLLM(_Echo(), steps).complete("hi", system="sys", task="audit")
    assert steps[0]["module"] == "DocumentAuditor"
    assert steps[0]["prompt"] == {"System_prompt": "sys", "User_prompt": "hi"}
    assert steps[0]["response"] == {"ok": True}
    assert "usage" not in steps[0]  # no usage() on the inner provider -> key omitted

    class _Metered:
        name = "metered"
        def __init__(self):
            self._n = 0
        def complete(self, prompt, *, system=None, **kw):  # noqa: ANN001
            self._n += 1
            return json.dumps({"call": self._n})
        def usage(self):
            return {"in": self._n * 10, "out": self._n * 2}

    steps2: list[dict] = []
    metered_llm = RecordingLLM(_Metered(), steps2)
    metered_llm.complete("a", task="audit")
    metered_llm.complete("b", task="audit")
    assert steps2[0]["usage"] == {"in": 10, "out": 2}  # per-call delta, not cumulative
    assert steps2[1]["usage"] == {"in": 10, "out": 2}

    assert _as_obj('{"a": 1}\n{"b": 2}') == [{"a": 1}, {"b": 2}]  # concatenated objects
    assert _as_obj('{"a": 1} trailing prose') == '{"a": 1} trailing prose'  # stays faithful
    assert _as_obj("not json at all") == "not json at all"
    print("recording_llm self-check ok")
