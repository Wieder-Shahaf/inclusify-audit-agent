"""Contract tests for the GUI-facing `/api/ui/execute` endpoint and the served GUI.

Same anti-tautology rule as test_api.py: assert response *shapes* and cross-field
invariants (report validity, span/quote integrity), never MockLLM's literal strings.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from inclusify_agent.report import validate_v2
from inclusify_agent.server import app
from inclusify_agent.server.recording_llm import MODULE_BY_TASK

client = TestClient(app)
KNOWN_MODULES = set(MODULE_BY_TASK.values()) | {"Agent"}
FIXTURE = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "sample.txt"

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", s).strip().lower()


def _assert_step_schema(step: dict) -> None:
    assert set(step.keys()) >= {"module", "prompt", "response"}
    assert step["module"] in KNOWN_MODULES
    assert set(step["prompt"].keys()) == {"System_prompt", "User_prompt"}
    assert isinstance(step["prompt"]["System_prompt"], str)
    assert isinstance(step["prompt"]["User_prompt"], str)


def test_ui_execute_ok_contract_on_fixture():
    text = FIXTURE.read_text(encoding="utf-8")
    r = client.post("/api/ui/execute", json={"prompt": text})
    assert r.status_code == 200
    body = r.json()

    assert set(body.keys()) == {"status", "error", "response", "steps", "report", "ui"}
    assert body["status"] == "ok"
    assert body["error"] is None
    assert isinstance(body["response"], str) and body["response"]

    assert body["steps"], "a fixture with known lexicon terms must trigger LLM calls"
    for step in body["steps"]:
        _assert_step_schema(step)

    report = body["report"]
    validate_v2(report)  # raises ReportSchemaError on the first violation

    ui = body["ui"]
    assert isinstance(ui["duration_s"], float)
    assert ui["duration_s"] >= 0

    finding_ids = {f["id"] for f in report["findings"]}
    kept_ids = {f["id"] for f in report["findings"] if not f["retracted"]}

    occurrences = ui["occurrences"]
    assert set(occurrences) <= finding_ids
    assert kept_ids <= set(occurrences), "every kept finding must have its spans in ui.occurrences"
    for occs in occurrences.values():
        assert isinstance(occs, list) and occs
        for pair in occs:
            assert isinstance(pair, list) and len(pair) == 2
            start, end = pair
            assert isinstance(start, int) and isinstance(end, int)
            assert 0 <= start < end <= len(text)

    rejected_keys = {"quote", "offsets", "occurrences", "category", "explanation", "confidence"}
    for rej in ui["rejected"]:
        assert rejected_keys <= set(rej)
        assert len(rej["offsets"]) == 2


def test_ui_execute_quote_integrity_on_fixture():
    """Every occurrence span, sliced from the raw submitted text, must normalize
    (whitespace/case) to that finding's own quote -- the frontend highlights the raw
    text at these exact offsets, so any drift here would mis-highlight in the GUI."""
    text = FIXTURE.read_text(encoding="utf-8")
    body = client.post("/api/ui/execute", json={"prompt": text}).json()
    report, ui = body["report"], body["ui"]
    by_id = {f["id"]: f for f in report["findings"]}

    assert ui["occurrences"], "the fixture must produce at least one confirmed finding"
    for fid, occs in ui["occurrences"].items():
        quote = by_id[fid]["quote"]
        for start, end in occs:
            occ_text = text[start:end]
            assert _norm(occ_text) == _norm(quote), (
                f"finding {fid!r}: occurrence ({start},{end}) = {occ_text!r} != quote {quote!r}"
            )


def test_ui_execute_empty_prompt_errors_no_500():
    r = client.post("/api/ui/execute", json={"prompt": "   "})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert body["error"]
    assert body["response"] is None
    assert body["steps"] == []
    assert body["report"] is None
    assert body["ui"] is None


def test_ui_execute_clean_document_has_no_findings():
    r = client.post("/api/ui/execute", json={
        "prompt": "The committee reviewed the proposal and approved the budget for next semester.",
    })
    body = r.json()
    assert body["status"] == "ok"
    validate_v2(body["report"])
    assert body["report"]["summary"]["confirmed"] == 0
    assert body["report"]["findings"] == []
    assert body["ui"]["occurrences"] == {}


def test_execute_contract_still_exactly_four_keys():
    """/api/execute's wire contract (course spec) must stay untouched by the new route."""
    r = client.post("/api/execute", json={"prompt": "The chairman approved the budget."})
    assert r.status_code == 200
    assert set(r.json().keys()) == {"status", "error", "response", "steps"}


def test_execute_ui_param_returns_superset():
    """`/api/execute?ui=1` (the GUI's Run-button call, spec §3) must return the same
    superset shape as `/api/ui/execute` — one pipeline run, structured view."""
    r = client.post("/api/execute?ui=1", json={"prompt": "The chairman approved the budget."})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"status", "error", "response", "steps", "report", "ui"}
    assert body["status"] == "ok"
    validate_v2(body["report"])
    for key in ("occurrences", "rejected", "stats", "duration_s", "tokens_in", "tokens_out"):
        assert key in body["ui"]


def test_health_has_extended_keys():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["llm"], str)
    for key in ("model", "embeddings", "vector_store", "persistence", "eric_live"):
        assert key in body
    assert isinstance(body["eric_live"], bool)


def test_gui_served_is_the_new_broadsheet_page():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    html = r.text
    assert "Inclusify" in html
    for label in (">Audit<", ">Agent<", ">Metrics<", ">Team<"):
        assert label in html
    assert "/api/execute?ui=1" in html  # spec §3: the Run button posts to /api/execute
    assert "Run Agent" in html  # spec §3's literal button label
    assert "Raw response" in html  # the exact /api/execute response string is viewable
