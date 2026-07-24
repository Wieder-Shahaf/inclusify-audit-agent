"""Phase 7 eval tests (BUILD_PLAN §6, P7)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from eval.baseline import run_baseline
from eval.gold import GOLD, score
from inclusify_agent.providers.llm import MockLLM

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_gold_set_size_nonzero() -> None:
    assert len(GOLD) >= 4


def test_score_perfect_predictions() -> None:
    preds = [g.expected_flag for g in GOLD]
    m = score(preds, GOLD)
    assert m["precision"] == 1.0
    assert m["recall"] == 1.0
    assert m["f1"] == 1.0


def test_score_all_false_predictions() -> None:
    preds = [False for _ in GOLD]
    m = score(preds, GOLD)
    assert m["tp"] == 0
    assert m["fp"] == 0


def test_baseline_runs_and_flags_known() -> None:
    out = run_baseline("The chairman approved the budget.", llm=MockLLM())
    assert "findings" in out
    assert "trace" in out
    assert any(f.label == "flag" for f in out["findings"])


def test_baseline_trace_has_no_reflect_or_ask() -> None:
    """The fixed pipeline must not emit ask_user or reflect events — that's its
    point: only the agent's autonomy adds those control-flow types."""
    out = run_baseline("The chairman approved.", llm=MockLLM())
    tools = {ev.get("tool") for ev in out["trace"]}
    assert "ask_user" not in tools
    nodes = {ev.get("node") for ev in out["trace"]}
    assert "reflect" not in nodes


def test_eval_cli_emits_divergence_and_exits_zero() -> None:
    """BUILD_PLAN §6 P7 exit check (v2, BUILD_PLAN R7):
    `python -m eval.run --mock` exits 0 AND prints control-flow divergence."""
    result = subprocess.run(
        [sys.executable, "-m", "eval.run", "--mock"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    report = json.loads(result.stdout)
    only_agent = report["control_flow_divergence"]["agent_only_event_types"]
    assert only_agent, "no agent-only events — autonomy claim unsupported"
    # v2's DocumentAuditor reads a whole window and flags candidates ("flag") --
    # the fixed baseline (chunk -> lexicon -> classify) never takes that step.
    assert set(only_agent) & {"flag"}


def test_eval_cli_doc_gold_mock_exits_zero(tmp_path) -> None:
    """BUILD_PLAN R7 exit check: `--gold doc --mock` runs the full v2 pipeline
    (run_v2) end to end and exits 0, printing span metrics + wall-clock + LLM-call
    count. Real Achva gold data is local-only/gitignored, so this uses a tiny
    synthetic doc_gold.json fixture via --gold-path, same shape as scripts/
    extract_gold_pdf.py's output (fulltext + char-offset spans)."""
    gold_path = tmp_path / "doc_gold.json"
    gold_path.write_text(json.dumps({
        "fulltext": "The chairman called the meeting to order.",
        "spans": [{"char_start": 4, "char_end": 12, "labels": ["biased"]}],
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "eval.run", "--mock", "--gold", "doc",
         "--gold-path", str(gold_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    report = json.loads(result.stdout)
    assert report["gold_set"] == "doc"
    assert "precision" in report["metrics"]["micro"]
    assert report["wall_clock_s"] >= 0
    assert report["llm_calls"] >= 1  # at least one DocumentAuditor call


def test_eval_cli_doc_gold_live_path_falls_back_offline(tmp_path) -> None:
    """`--gold doc` without --mock still exits 0 with no .env (config.build_llm()
    degrades to MockLLM) -- this is the code path that runs the FULL fulltext
    (no [:4000] truncation) through run_v2, exercised here with no live keys."""
    gold_path = tmp_path / "doc_gold.json"
    gold_path.write_text(json.dumps({
        "fulltext": "The committee approved the budget for the new laptops.",
        "spans": [],
    }), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "eval.run", "--gold", "doc", "--gold-path", str(gold_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"exit {result.returncode}: {result.stderr}"
    report = json.loads(result.stdout)
    assert report["predicted_spans"] == 0  # clean text, nothing to flag
