"""Eval entrypoint.

Usage:
    python -m eval.run --mock           # offline, uses MockLLM + InMemoryStore
    python -m eval.run                  # uses env-configured providers

Prints:
- Agent metrics: precision/recall/f1 on the synthetic gold set.
- Baseline metrics: same numbers via the fixed pipeline.
- Control-flow divergence: trace event types present in agent but not in baseline
  (the offline proof that autonomy changes outcomes — agent emits `ask` and
  `retract`, baseline does not).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from inclusify_agent.agent import run_audit
from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore

from .baseline import run_baseline
from .gold import GOLD, score


def _agent_predict(item_text: str, *, llm: Any, store: Any, embedder: Any) -> bool:
    final = run_audit(item_text, llm=llm, embedder=embedder, store=store, max_iters=50)
    # An item is "flagged by the agent" iff at least one non-retracted finding is label=flag.
    return any(f.label == "flag" and not f.retracted for f in final["findings"])


def _baseline_predict(item_text: str, *, llm: Any) -> bool:
    out = run_baseline(item_text, llm=llm)
    return any(f.label == "flag" for f in out["findings"])


def _agent_trace_events(text: str, *, llm: Any, store: Any, embedder: Any) -> list[str]:
    final = run_audit(text, llm=llm, embedder=embedder, store=store, max_iters=50)
    # Collect event 'kinds': (node, tool) tuples reduced to interesting types.
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
    # Baseline has no reflect, no ask_user.
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval.run")
    parser.add_argument("--mock", action="store_true",
                        help="Force MockLLM + InMemoryStore + HashEmbeddings.")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if not args.mock:
        print("note: --mock not set; using env providers (LLM_PROVIDER etc.). "
              "Offline default is still MockLLM/hash/chroma.", file=sys.stderr)

    llm = MockLLM()
    embedder = HashEmbeddings(dim=32)
    # Seed the store with one weak grounding doc so agentic-RAG has something
    # to find (and to fail to ground well — triggering retract).
    store = InMemoryStore(dim=32)
    store.add(
        ids=["g1"],
        vectors=embedder.embed("inclusive academic writing guidelines"),
        texts=["Prefer inclusive alternatives in academic writing."],
    )

    # Agent predictions
    agent_preds = [_agent_predict(g.text, llm=llm, store=store, embedder=embedder) for g in GOLD]
    agent_metrics = score(agent_preds, GOLD)

    # Baseline predictions
    baseline_preds = [_baseline_predict(g.text, llm=llm) for g in GOLD]
    baseline_metrics = score(baseline_preds, GOLD)

    # Control-flow divergence (BUILD_PLAN §6 P7): trace event types only the agent emits.
    sample_text = " ".join(g.text for g in GOLD[:3])
    agent_events = set(_agent_trace_events(sample_text, llm=llm, store=store, embedder=embedder))
    baseline_events = set(_baseline_trace_events(sample_text, llm=llm))
    only_agent = sorted(agent_events - baseline_events)

    report = {
        "gold_size": len(GOLD),
        "agent": agent_metrics,
        "baseline": baseline_metrics,
        "control_flow_divergence": {
            "agent_only_event_types": only_agent,
            "shared_event_types": sorted(agent_events & baseline_events),
            "baseline_only_event_types": sorted(baseline_events - agent_events),
        },
    }
    print(json.dumps(report, indent=2))

    # Exit 0 only if the agent's control flow demonstrably differs.
    if not only_agent:
        print("FAIL: agent emitted no events absent from the fixed pipeline baseline.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
