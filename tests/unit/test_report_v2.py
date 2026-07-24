"""Unit tests for the v2 report renderer (PRD §9, BUILD_PLAN R6): `render_v2`,
`to_markdown_v2`, `validate_v2`. v1's `render`/`to_markdown`/`validate` are covered
by `tests/unit/test_report.py` and stay untouched (legacy `eval/` harness).

Anti-tautology: findings are built directly from `Investigation`/`Candidate`
dataclasses and a hand-built `consolidation` dict -- never a full pipeline run --
so each test isolates one rendering/ordering/validation rule.
"""
from __future__ import annotations

import pytest

from inclusify_agent.report import ReportSchemaError, render_v2, to_markdown_v2, validate_v2
from inclusify_agent.tools import Candidate, Investigation


def _inv(
    id_: str, *, verdict="confirmed", category="gendered", confidence="medium",
    quote="chairman", secondary=None, evidence=None, needs_review=False,
    occurrences=None,
) -> Investigation:
    candidate = Candidate(
        id=id_, quote=quote, char_start=10, char_end=10 + len(quote),
        category=category, reason=f"contains: {quote}", lexicon_backed=True,
        window_id="w0", sentence_id="s0", occurrences=occurrences or [],
    )
    return Investigation(
        candidate=candidate, verdict=verdict, category=category,
        secondary_category=secondary, explanation="grounded explanation [1]",
        rewrite="chairperson", confidence=confidence, needs_human_review=needs_review,
        evidence=evidence or [], turns=2, forced=False,
    )


def _stats(investigations: list[Investigation]) -> dict:
    confirmed = sum(1 for i in investigations if i.verdict == "confirmed")
    return {
        "windows": 1, "candidates": len(investigations), "confirmed": confirmed,
        "rejected": len(investigations) - confirmed,
        "needs_human_review": sum(1 for i in investigations if i.needs_human_review),
    }


def _v2_result(investigations: list[Investigation]) -> dict:
    return {"investigations": investigations, "stats": _stats(investigations)}


def _consolidation(kept, retracted=(), patterns=()) -> dict:
    return {
        "kept": list(kept),
        "retracted": [{"id": i, "rationale": r} for i, r in retracted],
        "patterns": list(patterns),
        "summary": "summary", "skipped": False,
    }


_EVIDENCE = [{
    "id": "eric1", "text": "supporting passage " * 20, "score": 0.61, "n": 1,
    "metadata": {"title": "Gendered Titles", "year": "2021", "url": "https://eric.ed.gov/?id=1",
                 "source": "eric"},
}]


# ---- render_v2: ordering + shape ------------------------------------------------------------

def test_findings_ordered_by_consolidator_kept_order_then_retracted_last() -> None:
    invs = [_inv("c1", category="gendered"), _inv("c2", category="biased"),
            _inv("c3", category="ableist")]
    report = render_v2(
        _v2_result(invs),
        _consolidation(kept=["c2", "c3"], retracted=[("c1", "weak grounding")]),
    )

    ids = [f["id"] for f in report["findings"]]
    assert ids == ["c2", "c3", "c1"]
    assert report["findings"][0]["retracted"] is False
    assert report["findings"][-1]["retracted"] is True
    assert report["findings"][-1]["retraction_rationale"] == "weak grounding"
    assert report["findings"][0]["retraction_rationale"] is None


def test_rejected_investigations_never_become_findings() -> None:
    invs = [_inv("c1", verdict="confirmed"), _inv("c2", verdict="rejected")]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))

    assert [f["id"] for f in report["findings"]] == ["c1"]
    assert report["summary"]["rejected"] == 1
    assert report["summary"]["confirmed"] == 1


def test_summary_retracted_count_and_patterns_pass_through() -> None:
    invs = [_inv("c1"), _inv("c2")]
    report = render_v2(
        _v2_result(invs),
        _consolidation(
            kept=["c1"], retracted=[("c2", "dup")],
            patterns=[{"framing": "recurring gendered phrasing", "category": "gendered",
                       "finding_ids": ["c1"]}],
        ),
    )

    assert report["summary"]["retracted"] == 1
    assert report["summary"]["patterns"] == 1
    assert report["patterns"][0]["framing"] == "recurring gendered phrasing"


def test_finding_fields_match_investigation_and_candidate() -> None:
    invs = [_inv("c1", quote="chairman", occurrences=[(10, 18), (50, 58)], evidence=_EVIDENCE)]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))

    f = report["findings"][0]
    assert f["quote"] == "chairman"
    assert f["offsets"] == [10, 18]  # candidate.char_start/char_end (10, 10+len("chairman"))
    assert f["occurrences"] == 2
    assert f["category"] == "gendered"
    assert f["rewrite"] == "chairperson"
    assert f["grounded"] is True
    assert f["evidence"][0]["title"] == "Gendered Titles"
    assert f["evidence"][0]["snippet"] == _EVIDENCE[0]["text"][:300]


def test_finding_ungrounded_when_no_evidence() -> None:
    invs = [_inv("c1", evidence=[])]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    assert report["findings"][0]["grounded"] is False
    assert report["findings"][0]["evidence"] == []


def test_clean_doc_zero_investigations_yields_zero_findings() -> None:
    report = render_v2(_v2_result([]), _consolidation(kept=[]))
    assert report["findings"] == []
    assert report["version"] == "2.0"
    assert report["language"] == "en"


# ---- validate_v2 ----------------------------------------------------------------------------

def test_validate_v2_passes_on_a_well_formed_report() -> None:
    invs = [_inv("c1", evidence=_EVIDENCE)]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    validate_v2(report)  # must not raise


def test_validate_v2_passes_on_the_clean_doc_report() -> None:
    validate_v2(render_v2(_v2_result([]), _consolidation(kept=[])))


def test_validate_v2_rejects_missing_top_level_key() -> None:
    with pytest.raises(ReportSchemaError, match="missing top-level"):
        validate_v2({"version": "2.0"})


def test_validate_v2_rejects_wrong_version() -> None:
    report = render_v2(_v2_result([]), _consolidation(kept=[]))
    report["version"] = "1.0"
    with pytest.raises(ReportSchemaError, match="version"):
        validate_v2(report)


def test_validate_v2_rejects_bad_confidence() -> None:
    invs = [_inv("c1")]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    report["findings"][0]["confidence"] = "extreme"
    with pytest.raises(ReportSchemaError, match="confidence"):
        validate_v2(report)


def test_validate_v2_rejects_bad_offsets() -> None:
    invs = [_inv("c1")]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    report["findings"][0]["offsets"] = [10, 19, 30]
    with pytest.raises(ReportSchemaError, match="offsets"):
        validate_v2(report)


def test_validate_v2_rejects_finding_missing_a_key() -> None:
    invs = [_inv("c1")]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    del report["findings"][0]["explanation"]
    with pytest.raises(ReportSchemaError, match="missing key"):
        validate_v2(report)


# ---- to_markdown_v2 ---------------------------------------------------------------------------

def test_markdown_includes_quote_category_why_evidence_and_rewrite() -> None:
    invs = [_inv("c1", quote="chairman", category="gendered", evidence=_EVIDENCE)]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    md = to_markdown_v2(report)

    assert '"chairman"' in md
    assert "[gendered]" in md
    assert "Why" in md
    assert "grounded explanation [1]" in md
    assert "Gendered Titles (2021)" in md
    assert "Suggested rewrite" in md and "chairperson" in md
    assert "confidence=medium" in md


def test_markdown_shows_explicit_ungrounded_marker_when_no_evidence() -> None:
    invs = [_inv("c1", evidence=[])]
    report = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    md = to_markdown_v2(report)
    assert "ungrounded" in md.lower()


def test_markdown_retracted_section_carries_rationale() -> None:
    invs = [_inv("c1", quote="chairman"), _inv("c2", quote="freshmen")]
    report = render_v2(
        _v2_result(invs),
        _consolidation(kept=["c2"], retracted=[("c1", "contradicts doctrine")]),
    )
    md = to_markdown_v2(report)

    assert "Retracted during review" in md
    assert "contradicts doctrine" in md
    kept_section, retracted_section = md.split("Retracted during review")
    assert '"freshmen"' in kept_section        # the kept finding is in the numbered list
    assert '"chairman"' not in kept_section    # the retracted one is NOT
    assert '"chairman"' in retracted_section   # ...it only shows up in the retracted section


def test_markdown_patterns_section_only_when_patterns_exist() -> None:
    invs = [_inv("c1")]
    report_no_patterns = render_v2(_v2_result(invs), _consolidation(kept=["c1"]))
    assert "Recurring patterns" not in to_markdown_v2(report_no_patterns)

    report_with_patterns = render_v2(
        _v2_result(invs),
        _consolidation(kept=["c1"], patterns=[
            {"framing": "recurring gendered phrasing", "category": "gendered",
             "finding_ids": ["c1"]},
        ]),
    )
    md = to_markdown_v2(report_with_patterns)
    assert "Recurring patterns" in md
    assert "recurring gendered phrasing" in md


def test_markdown_clean_doc_says_no_issues_confirmed() -> None:
    report = render_v2(_v2_result([]), _consolidation(kept=[]))
    md = to_markdown_v2(report)
    assert "No inclusivity issues were confirmed" in md
    assert "## Findings" not in md
