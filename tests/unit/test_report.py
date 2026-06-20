"""Phase 6 report renderer + schema validator tests."""
from __future__ import annotations

import json

from inclusify_agent.agent import run_audit
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore
from inclusify_agent.report import (
    REPORT_VERSION,
    ReportSchemaError,
    render,
    to_markdown,
    validate,
)


def _run_real_audit() -> dict:
    emb = HashEmbeddings(dim=32)
    store = InMemoryStore(dim=32)
    store.add(
        ids=["g1"],
        vectors=emb.embed("inclusive language guideline"),
        texts=["Prefer chairperson over chairman."],
    )
    text = "The chairman approved. Each student brought his laptop."
    return run_audit(text, llm=MockLLM(), embedder=emb, store=store, max_iters=30)


def test_render_returns_schema_valid_dict() -> None:
    final = _run_real_audit()
    report = render(final)
    validate(report)
    assert report["version"] == REPORT_VERSION
    assert "findings" in report
    assert "trace" in report
    assert "stats" in report


def test_render_is_json_serializable() -> None:
    final = _run_real_audit()
    report = render(final)
    s = json.dumps(report, default=str)
    parsed = json.loads(s)
    assert parsed["version"] == REPORT_VERSION
    assert parsed["stats"]["findings_total"] == len(parsed["findings"])


def test_validate_rejects_bad_label() -> None:
    bad = {
        "version": REPORT_VERSION,
        "document": {"text_chars": 0},
        "findings": [{
            "id": "f1", "chunk_id": "c0", "span": "x", "label": "wrong",
            "category": None, "reason": "r", "confidence": "high",
            "grounded": False, "asked": False, "retracted": False,
        }],
        "stats": {"findings_total": 1, "retracted": 0, "asked": 0, "grounded": 0},
        "trace": [],
    }
    import pytest
    with pytest.raises(ReportSchemaError, match="label"):
        validate(bad)


def test_validate_rejects_missing_keys() -> None:
    import pytest
    with pytest.raises(ReportSchemaError, match="missing top-level"):
        validate({"version": REPORT_VERSION})


def test_to_markdown_includes_findings() -> None:
    final = _run_real_audit()
    report = render(final)
    md = to_markdown(report)
    assert "Inclusify audit report" in md
    assert f"Findings:** {report['stats']['findings_total']}" in md


def test_render_stats_counts_match_findings() -> None:
    final = _run_real_audit()
    report = render(final)
    assert report["stats"]["findings_total"] == len(report["findings"])
    assert report["stats"]["retracted"] == sum(1 for f in report["findings"] if f["retracted"])
    assert report["stats"]["asked"] == sum(1 for f in report["findings"] if f["asked"])
