"""Contract tests for the assignment-required HTTP endpoints.

Asserts the response *shapes* the spec mandates — not MockLLM literals — so the
contract holds when providers are swapped for the live course stack.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from inclusify_agent.server import app
from inclusify_agent.server.recording_llm import MODULE_BY_TASK

client = TestClient(app)
KNOWN_MODULES = set(MODULE_BY_TASK.values()) | {"Agent"}


def _assert_step_schema(step: dict) -> None:
    assert set(step.keys()) >= {"module", "prompt", "response"}
    assert step["module"] in KNOWN_MODULES
    assert set(step["prompt"].keys()) == {"System_prompt", "User_prompt"}
    assert isinstance(step["prompt"]["System_prompt"], str)
    assert isinstance(step["prompt"]["User_prompt"], str)


def test_team_info_shape():
    r = client.get("/api/team_info")
    assert r.status_code == 200
    body = r.json()
    assert {"group_batch_order_number", "team_name", "students"} <= set(body)
    assert len(body["students"]) == 2
    for s in body["students"]:
        assert s["name"] and "@" in s["email"]


def test_agent_info_shape():
    r = client.get("/api/agent_info")
    assert r.status_code == 200
    body = r.json()
    assert {"description", "purpose", "prompt_template", "prompt_examples"} <= set(body)
    assert "template" in body["prompt_template"]
    assert body["prompt_examples"], "must include at least one example"
    ex = body["prompt_examples"][0]
    assert {"prompt", "full_response", "steps"} <= set(ex)
    for step in ex["steps"]:
        _assert_step_schema(step)
        # Example steps mirror the bare /api/execute wire exactly (gen_examples.py
        # applies the same _spec_steps projection).
        assert set(step.keys()) == {"module", "prompt", "response"}


def test_execute_ok_contract():
    r = client.post("/api/execute",
                    json={"prompt": "The chairman told the freshmen manpower was short."})
    assert r.status_code == 200
    body = r.json()
    # Top-level fields must match the spec exactly.
    assert set(body.keys()) == {"status", "error", "response", "steps"}
    assert body["status"] == "ok"
    assert body["error"] is None
    assert isinstance(body["response"], str) and body["response"]
    assert isinstance(body["steps"], list) and body["steps"]
    for step in body["steps"]:
        _assert_step_schema(step)
        # Bare /api/execute steps are EXACTLY the spec schema; the usage superset
        # key lives on ?ui=1 (the GUI's ledger) only.
        assert set(step.keys()) == {"module", "prompt", "response"}


def test_execute_logs_every_llm_call():
    """steps must trace each v2 LLM module the pipeline invoked."""
    r = client.post("/api/execute",
                    json={"prompt": "The chairman approved the budget."})
    mods = {s["module"] for s in r.json()["steps"]}
    # DocumentAuditor always runs on a non-empty prompt; "chairman" is a lexicon-backed
    # candidate MockLLM's investigate script always ends up confirming (weak-evidence
    # fallback if the corpus has nothing better), so EvidenceInvestigator runs too --
    # and a confirmed finding always triggers ReportConsolidator.
    assert {"DocumentAuditor", "EvidenceInvestigator", "ReportConsolidator"} <= mods


def test_execute_empty_prompt_errors():
    r = client.post("/api/execute", json={"prompt": "   "})
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]
    assert body["response"] is None
    assert body["steps"] == []


def test_execute_malformed_body_returns_error_envelope():
    """Spec §C: even a malformed request body gets the in-band error envelope,
    never FastAPI's default 422 {"detail": ...} — a grader POSTing garbage must
    see the same four keys as any other agent error."""
    cases = [
        dict(),                                                # no body at all
        dict(content=b"this is not json",
             headers={"Content-Type": "application/json"}),   # invalid JSON
        dict(json={"wrong_key": "x"}),                         # missing "prompt"
        dict(json="just a string"),                            # non-object JSON body
    ]
    for kwargs in cases:
        r = client.post("/api/execute", **kwargs)
        assert r.status_code == 200, kwargs
        body = r.json()
        assert set(body.keys()) == {"status", "error", "response", "steps"}, kwargs
        assert body["status"] == "error"
        assert isinstance(body["error"], str) and body["error"]
        assert body["response"] is None
        assert body["steps"] == []


def test_validation_envelope_scoped_to_execute_routes():
    # Non-spec routes keep FastAPI's default validation behavior (422 + detail).
    r = client.post("/api/why", json={"no_span_here": 1})
    assert r.status_code == 422


def test_spec_steps_strips_usage_superset():
    """The wire strip that keeps bare /api/execute steps exactly {module, prompt,
    response} when a live metered provider adds per-call usage."""
    from inclusify_agent.server.app import _spec_steps

    metered = [{"module": "DocumentAuditor",
                "prompt": {"System_prompt": "s", "User_prompt": "u"},
                "response": {"ok": True}, "usage": {"in": 10, "out": 2}}]
    assert _spec_steps(metered) == [{"module": "DocumentAuditor",
                                     "prompt": {"System_prompt": "s", "User_prompt": "u"},
                                     "response": {"ok": True}}]


def test_why_ok_contract():
    r = client.post("/api/why", json={
        "span": "The chairman told the freshmen manpower was short.",
        "category": "gendered",
    })
    assert r.status_code == 200
    body = r.json()
    assert {"status", "error", "explanation", "citations",
            "augmented_prompt", "steps"} <= set(body)
    assert body["status"] == "ok"
    assert isinstance(body["explanation"], str) and body["explanation"]
    assert isinstance(body["citations"], list)
    for c in body["citations"]:
        assert {"id", "text", "score", "metadata"} <= set(c)
    for step in body["steps"]:
        _assert_step_schema(step)
    # /api/why is a single-finding EvidenceInvestigator run (PRD §4 module map).
    assert any(s["module"] == "EvidenceInvestigator" for s in body["steps"])


def test_why_empty_span_errors():
    r = client.post("/api/why", json={"span": "   "})
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]
    assert body["steps"] == []


def test_model_architecture_is_png():
    r = client.get("/api/model_architecture")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_gui_served_at_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
