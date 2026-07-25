"""Eval entrypoint.

Usage:
    python -m eval.run --mock                       # synthetic gold + MockLLM (offline)
    python -m eval.run --mock --gold synthetic      # same as default
    python -m eval.run --mock --gold achva-en       # Achva EN-only against MockLLM
    python -m eval.run --gold achva-en              # Achva EN-only against env LLM (live)
    python -m eval.run --gold achva                 # Achva both languages
    python -m eval.run --mock --gold doc            # document-level Achva gold (mock; plumbing)
    python -m eval.run --gold doc --gold-path <p>   # ditto, live providers / a custom gold file

Prints:
- Agent metrics: precision/recall/f1 on the gold set.
- Baseline metrics: same numbers via the fixed pipeline.
- Per-label breakdown when --gold achva* (true/false rates split by Achva category).
- Control-flow divergence: trace event types present in agent but not in baseline --
  informational only (v1-era P7 check); does not affect the exit code.
- --gold doc instead prints span-level P/R/F1 + fp-on-correct + label-agnostic
  span-detection P/R/F1 (eval.doc_gold.score), plus wall-clock and total LLM calls,
  plus windows_parse_failed (no-silent-caps: a window whose audit call never parsed,
  even after the repair retry, degrades to zero candidates -- a "warning" field
  appears when this is nonzero, since results are then a lower bound).

Exit code: 0 whenever metrics were computed and printed (both --gold doc and the
achva*/synthetic modes). Only argument errors / a missing gold file exit non-zero.

v2 (BUILD_PLAN R7): "agent" now means the v2 pipeline (`pipeline.audit_document` for
per-sentence gold, `pipeline.run_v2` for the document-level gold) -- the retired v1
ReAct graph is gone, from this harness and from the codebase entirely. The "baseline"
ablation (`eval.baseline.run_baseline`, a hard-coded chunk->lexicon->classify sequence
with no LLM judgment over a whole window) is untouched: it's still what v2's autonomy
must diverge from.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from inclusify_agent.pipeline import audit_document, run_v2
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore
from inclusify_agent.server.recording_llm import RecordingLLM

from .baseline import run_baseline
from .doc_gold import load_doc_gold
from .doc_gold import score as score_doc
from .gold import SYNTHETIC, GoldItem, load_achva, score


def _agent_predict(item_text: str, *, llm: Any) -> bool:
    """DocumentAuditor only, not the full run_v2 (BUILD_PLAN R7): a gold item is one
    sentence, so one window IS the whole "document" -- an Investigator tool loop per
    row would spend a corpus/live search call for no scoring benefit across the
    achva-en/achva sets' 40-100 rows."""
    result = audit_document(item_text, llm=llm)
    return len(result["candidates"]) > 0


def _baseline_predict(item_text: str, *, llm: Any) -> bool:
    out = run_baseline(item_text, llm=llm)
    return any(f.label == "flag" for f in out["findings"])


def _agent_trace_events(text: str, *, llm: Any) -> list[str]:
    """v2's DocumentAuditor has no branching control-flow actions (no reflect/retract,
    no clarifying-question step) -- the signal a fixed baseline never takes is a
    whole-window LLM read that flags a candidate."""
    result = audit_document(text, llm=llm)
    return [
        "flag" for ev in result["trace"]
        if ev.get("node") == "audit" and ev.get("detail", {}).get("candidates", 0) > 0
    ]


def _baseline_trace_events(text: str, *, llm: Any) -> list[str]:
    """The fixed-order baseline emits no agentic trace events by construction —
    kept as a real call so the informational divergence block stays honest."""
    run_baseline(text, llm=llm)
    return []


def _per_label_breakdown(
    gold: list[GoldItem], preds: list[bool],
) -> dict[str, dict[str, int]]:
    """Group prediction outcomes by expected_category (the Achva raw label)."""
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "flagged": 0})
    for g, p in zip(gold, preds, strict=True):
        cat = g.expected_category or "Correct"
        by_cat[cat]["n"] += 1
        if p:
            by_cat[cat]["flagged"] += 1
    return dict(by_cat)


def _load_gold(name: str) -> list[GoldItem]:
    if name == "synthetic":
        return list(SYNTHETIC)
    if name == "achva":
        gold = load_achva()
        if not gold:
            print("error: data/gold/achva_review_set.csv not found", file=sys.stderr)
            sys.exit(2)
        return gold
    if name == "achva-en":
        gold = load_achva(language="EN")
        if not gold:
            print("error: data/gold/achva_review_set.csv not found", file=sys.stderr)
            sys.exit(2)
        return gold
    if name == "achva-he":
        gold = load_achva(language="HE")
        if not gold:
            print("error: data/gold/achva_review_set.csv not found", file=sys.stderr)
            sys.exit(2)
        return gold
    print(f"error: unknown --gold value: {name!r}", file=sys.stderr)
    sys.exit(2)


def _build_providers(*, mock: bool) -> tuple[Any, Any, Any]:
    """The same mock-vs-live provider bootstrap every gold mode uses."""
    if mock:
        llm: Any = MockLLM()
        embedder: Any = HashEmbeddings(dim=32)
        store: Any = InMemoryStore(dim=32)
        store.add(
            ids=["g1"],
            vectors=embedder.embed("inclusive academic writing guidelines"),
            texts=["Prefer inclusive alternatives in academic writing."],
        )
    else:
        # Live: use env-configured providers (.env). Falls back to offline defaults
        # if env is not set — config.build_* enforces.
        from inclusify_agent import config
        llm = config.build_llm()
        embedder = config.build_embeddings()
        store = config.build_vector_store(dim=embedder.dim)
        print(f"using live providers: llm={llm.name} emb={embedder.name} "
              f"store={store.name}", file=sys.stderr)
    return llm, embedder, store


def _run_doc_gold(args: argparse.Namespace) -> int:
    """`--gold doc`: span-level P/R/F1 on the single annotated Achva paper, through
    the full v2 pipeline (DocumentAuditor -> EvidenceInvestigator -> ReportConsolidator).

    Mock mode keeps the [:4000] truncation (plumbing proof, fast); live mode runs the
    FULL fulltext -- `audit_document`'s own window-count guard still caps it.
    """
    gold_path = Path(args.gold_path)
    if not gold_path.exists():
        print(f"error: {gold_path} not found — run scripts/extract_gold_pdf.py first "
              "(expert data is local-only; see the data/gold/ .gitignore policy)",
              file=sys.stderr)
        return 2
    gold = load_doc_gold(gold_path)
    text = gold["fulltext"][:4000] if args.mock else gold["fulltext"]

    if args.mock:
        print("=== MOCK MODE — metrics are plumbing-only (real numbers land with live "
              "providers in R7) ===", file=sys.stderr)
    llm, embedder, store = _build_providers(mock=args.mock)

    steps: list[dict[str, Any]] = []
    recording_llm = RecordingLLM(llm, steps)
    t0 = time.monotonic()
    result = run_v2(text, llm=recording_llm, store=store, embedder=embedder)
    wall_clock_s = time.monotonic() - t0

    # Predicted spans = every occurrence of every KEPT (non-retracted) CONFIRMED
    # finding -- the consolidator's `kept` list of candidate ids is the source of
    # truth for "non-retracted", not just verdict=="confirmed" on its own.
    kept_ids = set(result["consolidation"]["kept"])
    predicted: list[dict[str, Any]] = []
    for inv in result["investigations"]:
        if inv.verdict != "confirmed" or inv.candidate.id not in kept_ids:
            continue
        for start, end in inv.candidate.occurrences:
            predicted.append({"char_start": start, "char_end": end, "category": inv.category})

    metrics = score_doc(predicted, gold["spans"], min_overlap=0.5)
    windows_parse_failed = result["stats"].get("windows_parse_failed", 0)
    report = {
        "gold_set": "doc",
        "gold_path": str(gold_path),
        "gold_spans": len(gold["spans"]),
        "predicted_spans": len(predicted),
        "metrics": metrics,
        "wall_clock_s": round(wall_clock_s, 2),
        "llm_calls": len(steps),
        "windows_parse_failed": windows_parse_failed,
    }
    if windows_parse_failed:
        report["warning"] = (
            f"{windows_parse_failed} windows returned unparseable output — "
            "results are a lower bound."
        )
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run")
    parser.add_argument("--mock", action="store_true",
                        help="Force MockLLM + InMemoryStore + HashEmbeddings (offline).")
    parser.add_argument("--gold", default="synthetic",
                        choices=("synthetic", "achva", "achva-en", "achva-he", "doc"),
                        help="Which gold set to evaluate against.")
    parser.add_argument("--gold-path", default="data/gold/achva/doc_gold.json",
                        help="Path to doc_gold.json (only used by --gold doc).")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.gold == "doc":
        return _run_doc_gold(args)

    gold = _load_gold(args.gold)
    if not gold:
        print("error: empty gold set", file=sys.stderr)
        return 2

    if args.mock:
        llm: Any = MockLLM()
        embedder: Any = HashEmbeddings(dim=32)
        store: Any = InMemoryStore(dim=32)
        store.add(
            ids=["g1"],
            vectors=embedder.embed("inclusive academic writing guidelines"),
            texts=["Prefer inclusive alternatives in academic writing."],
        )
    else:
        # Live: use env-configured providers (.env). Falls back to offline defaults
        # if env is not set — config.build_* enforces.
        from inclusify_agent import config
        llm = config.build_llm()
        embedder = config.build_embeddings()
        store = config.build_vector_store(dim=embedder.dim)
        print(f"using live providers: llm={llm.name} emb={embedder.name} "
              f"store={store.name}", file=sys.stderr)

    agent_preds = [_agent_predict(g.text, llm=llm) for g in gold]
    agent_metrics = score(agent_preds, gold)

    baseline_preds = [_baseline_predict(g.text, llm=llm) for g in gold]
    baseline_metrics = score(baseline_preds, gold)

    sample_text = " ".join(g.text for g in gold[:3])
    agent_events = set(_agent_trace_events(sample_text, llm=llm))
    baseline_events = set(_baseline_trace_events(sample_text, llm=llm))
    only_agent = sorted(agent_events - baseline_events)

    report: dict[str, Any] = {
        "gold_set": args.gold,
        "gold_size": len(gold),
        "agent": agent_metrics,
        "baseline": baseline_metrics,
        "control_flow_divergence": {
            "agent_only_event_types": only_agent,
            "shared_event_types": sorted(agent_events & baseline_events),
            "baseline_only_event_types": sorted(baseline_events - agent_events),
        },
    }
    if args.gold.startswith("achva"):
        report["per_label_agent"] = _per_label_breakdown(gold, agent_preds)
        report["per_label_baseline"] = _per_label_breakdown(gold, baseline_preds)

    print(json.dumps(report, indent=2))

    # control_flow_divergence is informational only (v1-era P7 acceptance check) --
    # it no longer gates the exit code. Whether the first 3 gold items happen to
    # produce a divergent event is corpus-content-dependent with a live LLM (unlike
    # MockLLM's tuned synthetic fixtures); the metrics above are the real deliverable.
    return 0


if __name__ == "__main__":
    sys.exit(main())
