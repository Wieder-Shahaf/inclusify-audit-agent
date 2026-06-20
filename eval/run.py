"""Eval entrypoint.

Usage:
    python -m eval.run --mock                       # synthetic gold + MockLLM (offline)
    python -m eval.run --mock --gold synthetic      # same as default
    python -m eval.run --mock --gold achva-en       # Achva EN-only against MockLLM
    python -m eval.run --gold achva-en              # Achva EN-only against env LLM (live)
    python -m eval.run --gold achva                 # Achva both languages

Prints:
- Agent metrics: precision/recall/f1 on the gold set.
- Baseline metrics: same numbers via the fixed pipeline.
- Per-label breakdown when --gold achva* (true/false rates split by Achva category).
- Control-flow divergence: trace event types present in agent but not in baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any

from inclusify_agent.agent import run_audit
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore

from .baseline import run_baseline
from .gold import SYNTHETIC, GoldItem, load_achva, score


def _agent_predict(item_text: str, *, llm: Any, store: Any, embedder: Any) -> bool:
    final = run_audit(item_text, llm=llm, embedder=embedder, store=store, max_iters=50)
    # An item is "flagged by the agent" iff at least one non-retracted finding is label=flag.
    return any(f.label == "flag" and not f.retracted for f in final["findings"])


def _baseline_predict(item_text: str, *, llm: Any) -> bool:
    out = run_baseline(item_text, llm=llm)
    return any(f.label == "flag" for f in out["findings"])


def _agent_trace_events(text: str, *, llm: Any, store: Any, embedder: Any) -> list[str]:
    final = run_audit(text, llm=llm, embedder=embedder, store=store, max_iters=50)
    events: list[str] = []
    for ev in final["trace"]:
        if ev.get("node") == "reflect" and ev.get("detail", {}).get("retracted_ids"):
            events.append("retract")
        if ev.get("tool") == "ask_user":
            events.append("ask")
    return events


def _baseline_trace_events(text: str, *, llm: Any) -> list[str]:
    out = run_baseline(text, llm=llm)
    events: list[str] = []
    for ev in out["trace"]:
        if ev.get("tool") in ("ask_user",):
            events.append("ask")
    return events


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run")
    parser.add_argument("--mock", action="store_true",
                        help="Force MockLLM + InMemoryStore + HashEmbeddings (offline).")
    parser.add_argument("--gold", default="synthetic",
                        choices=("synthetic", "achva", "achva-en", "achva-he"),
                        help="Which gold set to evaluate against.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

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

    agent_preds = [_agent_predict(g.text, llm=llm, store=store, embedder=embedder)
                   for g in gold]
    agent_metrics = score(agent_preds, gold)

    baseline_preds = [_baseline_predict(g.text, llm=llm) for g in gold]
    baseline_metrics = score(baseline_preds, gold)

    sample_text = " ".join(g.text for g in gold[:3])
    agent_events = set(_agent_trace_events(sample_text, llm=llm, store=store, embedder=embedder))
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

    # Exit 0 only if the agent's control flow demonstrably differs.
    if not only_agent:
        print("FAIL: agent emitted no events absent from the fixed pipeline baseline.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
