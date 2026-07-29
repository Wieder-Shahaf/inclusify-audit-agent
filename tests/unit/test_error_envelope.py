"""An upstream safety refusal must reach the user as a sentence, not provider JSON.

Structural invariants only (CLAUDE.md rule 5): status/keys unchanged, no provider
internals in `error`, non-refusal errors keep their diagnostic text. No copy literals
beyond the module's own constant.
"""
from __future__ import annotations

from inclusify_agent import config
from inclusify_agent.server.app import REFUSAL_MESSAGE, _friendly_error, execute_prompt

# Abridged from a real LLMod.ai/LiteLLM failure (2026-07-29): openai.BadRequestError
# carrying Azure's ResponsibleAIPolicyViolation blob.
AZURE_BLOB = (
    "Error code: 400 - {'error': {'message': \"litellm.BadRequestError: "
    "litellm.ContentPolicyViolationError: The response was filtered due to the prompt "
    "triggering Azure OpenAI's content management policy. Please modify your prompt and "
    "retry.\", 'code': '400', 'provider_specific_fields': {'innererror': {'code': "
    "'ResponsibleAIPolicyViolation', 'content_filter_result': {'hate': {'filtered': "
    "True, 'severity': 'medium'}}}}}}"
)

LEAK_MARKERS = ("litellm", "azure", "400", "responsibleai", "content_filter", "{")


class _RefusingLLM:
    name = "refusing"

    def complete(self, prompt: str, **kwargs: object) -> str:
        raise RuntimeError(AZURE_BLOB)


def test_refusal_blob_becomes_the_friendly_message() -> None:
    assert _friendly_error(RuntimeError(AZURE_BLOB)) == REFUSAL_MESSAGE


def test_other_markers_also_match() -> None:
    for msg in ("ContentPolicyViolationError: nope", "code: content_filter"):
        assert _friendly_error(RuntimeError(msg)) == REFUSAL_MESSAGE


def test_unrelated_exception_keeps_its_diagnostic_text() -> None:
    out = _friendly_error(TimeoutError("read timed out"))
    assert out == "TimeoutError: read timed out"


def test_execute_prompt_returns_envelope_with_no_provider_internals(monkeypatch) -> None:
    monkeypatch.setattr(config, "build_llm", _RefusingLLM)
    out = execute_prompt("The chairman told the freshmen that manpower was short.")

    assert set(out) == {"status", "error", "response", "steps", "tokens_in", "tokens_out"}
    assert out["status"] == "error"
    assert out["response"] is None
    assert out["error"] == REFUSAL_MESSAGE
    lowered = out["error"].lower()
    assert not any(m in lowered for m in LEAK_MARKERS), "provider internals leaked"
