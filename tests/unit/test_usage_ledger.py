"""R7 tests: the token/usage ledger (course req #1c: a visible budget).

Three layers, each with its own offline fake:
- `OpenAICompatLLM.usage()` accumulates across `complete()` calls on one instance
  (stub the lazy-imported openai client directly -- see openai_compat.py).
- `RecordingLLM` optionally threads per-step usage deltas into `steps[]`.
- `server/app.py::execute_prompt` appends a markdown footer + returns tokens_in/out
  for `api_execute` to log, but never leaks them into the HTTP wire contract, and
  never leaks totals across separate requests (a fresh provider is built per call).
"""
from __future__ import annotations

import importlib
import json

from inclusify_agent import config
from inclusify_agent.providers.llm import MockLLM, OpenAICompatLLM
from inclusify_agent.server.recording_llm import RecordingLLM

# `inclusify_agent.server.__init__` does `from .app import app`, which rebinds the
# package's `app` attribute to the FastAPI instance -- shadowing the submodule.
# `importlib.import_module` bypasses that shadow and gets the actual module (needed
# to call execute_prompt/api_execute directly and to monkeypatch its `_persistence`
# module global).
server_app = importlib.import_module("inclusify_agent.server.app")

# ---- fakes for the lazily-imported openai client (see OpenAICompatLLM._get_client) ----


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeResponse:
    def __init__(self, content: str, usage: _FakeUsage | None) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)

    def create(self, **kwargs) -> _FakeResponse:  # noqa: ANN003
        return self._responses.pop(0)


class _FakeChat:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.completions = _FakeCompletions(responses)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.chat = _FakeChat(responses)


# ---- OpenAICompatLLM.usage() -------------------------------------------------------

def test_openai_compat_usage_starts_at_zero() -> None:
    llm = OpenAICompatLLM(base_url="http://localhost", api_key="x", model="m")
    assert llm.usage() == {"in": 0, "out": 0}


def test_openai_compat_accumulates_usage_across_two_calls() -> None:
    llm = OpenAICompatLLM(base_url="http://localhost", api_key="x", model="m")
    llm._client = _FakeClient([
        _FakeResponse("first", _FakeUsage(10, 4)),
        _FakeResponse("second", _FakeUsage(7, 3)),
    ])
    assert llm.complete("hi", system="sys", task="audit") == "first"
    assert llm.usage() == {"in": 10, "out": 4}
    assert llm.complete("again", task="audit") == "second"
    assert llm.usage() == {"in": 17, "out": 7}  # cumulative, not per-call


def test_openai_compat_missing_usage_field_stays_zero() -> None:
    """Some OpenAI-compat providers omit `usage` on the response entirely."""
    llm = OpenAICompatLLM(base_url="http://localhost", api_key="x", model="m")
    llm._client = _FakeClient([_FakeResponse("ok", usage=None)])
    llm.complete("hi", task="audit")
    assert llm.usage() == {"in": 0, "out": 0}


# ---- RecordingLLM per-step usage passthrough (optional; server/recording_llm.py) ---

def test_recording_llm_adds_usage_delta_per_step_when_available() -> None:
    llm = OpenAICompatLLM(base_url="http://localhost", api_key="x", model="m")
    llm._client = _FakeClient([
        _FakeResponse("a", _FakeUsage(10, 4)),
        _FakeResponse("b", _FakeUsage(7, 3)),
    ])
    steps: list[dict] = []
    recording = RecordingLLM(llm, steps)
    recording.complete("hi", task="audit")
    recording.complete("again", task="audit")
    assert steps[0]["usage"] == {"in": 10, "out": 4}
    assert steps[1]["usage"] == {"in": 7, "out": 3}  # per-call delta, not cumulative


def test_recording_llm_omits_usage_key_without_inner_usage() -> None:
    steps: list[dict] = []
    RecordingLLM(MockLLM(), steps).complete("hi", task="audit")
    assert "usage" not in steps[0]


# ---- server/app.py::execute_prompt -------------------------------------------------

def test_execute_prompt_mock_llm_no_footer_and_tokens_none() -> None:
    """MockLLM (the offline default) has no usage() -- no footer, tokens are None."""
    result = server_app.execute_prompt("The chairman approved the budget.")
    assert result["status"] == "ok"
    assert "Tokens:" not in result["response"]
    assert result["tokens_in"] is None
    assert result["tokens_out"] is None


def test_api_execute_wire_contract_unchanged_and_logs_tokens_none(monkeypatch) -> None:
    """/api/execute's JSON body must stay exactly {status,error,response,steps}
    (course spec) even though execute_prompt's internal dict carries tokens_in/out
    for logging -- api_execute strips them before returning."""
    calls: list[dict] = []

    class _SpyPersistence:
        name = "spy"

        def log_run(self, *, prompt, status, response, steps,  # noqa: ANN001
                     tokens_in=None, tokens_out=None) -> None:  # noqa: ANN001
            calls.append({"tokens_in": tokens_in, "tokens_out": tokens_out})

    monkeypatch.setattr(server_app, "_persistence", _SpyPersistence())
    body = server_app.ExecuteIn(prompt="The chairman approved the budget.")
    out = server_app.api_execute(body)

    assert set(out.keys()) == {"status", "error", "response", "steps"}
    assert calls == [{"tokens_in": None, "tokens_out": None}]


class _FakeMeteredLLM:
    """A usage-bearing fake standing in for OpenAICompatLLM, shaped like MockLLM's
    'audit' task so a real run_v2 call resolves in exactly one `.complete()` --
    empty candidates skip the Investigator/Consolidator stages entirely (PRD §8's
    skip-if-empty lever), keeping the token count per request deterministic."""

    name = "fake_metered"

    def __init__(self) -> None:
        self.usage_in = 0
        self.usage_out = 0

    def complete(self, prompt: str, *, system: str | None = None, **kwargs) -> str:  # noqa: ANN003
        self.usage_in += 100
        self.usage_out += 20
        return json.dumps({"candidates": [], "hint_verdicts": []})

    def usage(self) -> dict[str, int]:
        return {"in": self.usage_in, "out": self.usage_out}


def test_execute_prompt_appends_footer_and_returns_tokens_when_usage_present(monkeypatch) -> None:
    monkeypatch.setattr(config, "build_llm", _FakeMeteredLLM)
    result = server_app.execute_prompt("The chairman approved the budget.")
    assert result["status"] == "ok"
    assert result["tokens_in"] == 100
    assert result["tokens_out"] == 20
    assert "\n\n---\n_Tokens: 100 in / 20 out (this audit)_" in result["response"]


def test_execute_prompt_builds_fresh_provider_per_request(monkeypatch) -> None:
    """execute_prompt calls config.build_llm() itself (verified: not a shared/cached
    provider) -- so usage totals never leak across separate /api/execute calls even
    though a single OpenAICompatLLM instance accumulates cumulatively."""
    built: list[_FakeMeteredLLM] = []

    def _fake_build_llm() -> _FakeMeteredLLM:
        inst = _FakeMeteredLLM()
        built.append(inst)
        return inst

    monkeypatch.setattr(config, "build_llm", _fake_build_llm)

    r1 = server_app.execute_prompt("The chairman approved the budget.")
    r2 = server_app.execute_prompt("The committee approved the budget.")

    assert len(built) == 2  # a fresh provider instance per call
    assert r1["tokens_in"] == 100 and r1["tokens_out"] == 20
    assert r2["tokens_in"] == 100 and r2["tokens_out"] == 20  # not 200/40 -- no leak
