"""Phase 6 CLI test: the documented exit command produces valid JSON."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "data" / "fixtures" / "sample.txt"


def test_cli_audit_emits_schema_valid_json(tmp_path: Path) -> None:
    """BUILD_PLAN §6 P6 exit check:
    `python -m inclusify_agent.cli audit data/fixtures/sample.txt --provider mock`
    emits valid JSON with findings + trace, exit 0.
    """
    out_file = tmp_path / "report.json"
    result = subprocess.run(
        [sys.executable, "-m", "inclusify_agent.cli", "audit", str(FIXTURE),
         "--provider", "mock", "--store", "inmemory", "--output", str(out_file)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI exited {result.returncode}: {result.stderr}"
    assert out_file.exists()
    report = json.loads(out_file.read_text(encoding="utf-8"))
    # Schema-shape sanity
    assert report["version"] == "1.0"
    assert "findings" in report
    assert "trace" in report
    assert "stats" in report
    assert isinstance(report["findings"], list)
    assert isinstance(report["trace"], list)
    # Phase 4 invariants still hold via the CLI path
    assert report["stats"]["findings_total"] >= 1


def test_cli_audit_markdown_format(tmp_path: Path) -> None:
    out_file = tmp_path / "report.md"
    result = subprocess.run(
        [sys.executable, "-m", "inclusify_agent.cli", "audit", str(FIXTURE),
         "--provider", "mock", "--store", "inmemory", "--format", "markdown",
         "--output", str(out_file)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0
    md = out_file.read_text(encoding="utf-8")
    assert "# Inclusify audit report" in md
