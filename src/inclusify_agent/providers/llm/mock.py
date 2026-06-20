"""Deterministic mock LLM driving the whole graph.

BUILD_PLAN §3: MockLLM is the offline keystone. It returns schema-valid outputs for
every call-site so the ReAct + Reflection + Agentic-RAG loop runs end-to-end with no
keys. The same prompt always yields the same response — tests can assert on the trace.

Call-site routing (by 'task' kwarg):
- task="classify"   → flag/skip decision JSON for a span
- task="route"      → next-tool decision (scripted ReAct sequence)
- task="reflect"    → drops one seeded false-positive
- task="rewrite"    → templated inclusive-rewrite JSON
- task="ground"     → returns "grounded" or "ungrounded" given a candidate citation

Output is always JSON-stringifiable text so the graph can `json.loads` it.
"""
from __future__ import annotations

import json
import re
from typing import Any


class MockLLM:
    name = "mock"

    def __init__(self) -> None:
        # Heuristic flags: words that the mock will always flag as biased.
        # Matched on word boundaries (\b) so "he" doesn't match "the", "his" not "this".
        self._flag_words = (
            "chairman", "manpower", "freshmen", "blacklist", "his", "he",
        )

    def complete(self, prompt: str, *, system: str | None = None, **kwargs: Any) -> str:
        task = kwargs.get("task", "")
        if task == "classify":
            return self._classify(prompt, **kwargs)
        if task == "route":
            return self._route(prompt, **kwargs)
        if task == "reflect":
            return self._reflect(prompt, **kwargs)
        if task == "rewrite":
            return self._rewrite(prompt, **kwargs)
        if task == "ground":
            return self._ground(prompt, **kwargs)
        # Fallback: echo the prompt deterministically so tests can detect "untasked" calls.
        return json.dumps({"echo": prompt[:120], "task": task or "unknown"})

    def _classify(self, prompt: str, **kwargs: Any) -> str:
        span = (kwargs.get("span") or prompt).lower()
        hits = [w for w in self._flag_words if re.search(rf"\b{re.escape(w)}\b", span)]
        if hits:
            gendered = {"chairman", "his", "he"}
            category = "gendered" if any(w in gendered for w in hits) else "exclusionary"
            return json.dumps({
                "label": "flag",
                "category": category,
                "reason": f"contains: {sorted(hits)[0]}",
            })
        return json.dumps({"label": "skip", "category": None, "reason": "no trigger"})

    def _route(self, prompt: str, **kwargs: Any) -> str:
        state_hint = kwargs.get("state_hint", "")
        # Deterministic scripted loop: chunk → lex → classify → retrieve → rewrite → reflect → stop
        order = ["chunk", "lexicon_lookup", "classify_span", "retrieve_citation",
                 "propose_rewrite", "reflect", "stop"]
        idx = int(kwargs.get("step", 0)) % len(order)
        return json.dumps({"tool": order[idx], "rationale": f"step {idx}: {state_hint[:60]}"})

    def _reflect(self, prompt: str, **kwargs: Any) -> str:
        findings = kwargs.get("findings", [])
        # Drop the first finding tagged as 'low_confidence' (seeds the retract event in the trace).
        kept, retracted = [], []
        dropped_one = False
        for f in findings:
            if not dropped_one and f.get("confidence") == "low":
                retracted.append(f.get("id"))
                dropped_one = True
                continue
            kept.append(f)
        return json.dumps({"kept": kept, "retracted": retracted})

    def _rewrite(self, prompt: str, **kwargs: Any) -> str:
        span = kwargs.get("span", "")
        # Order matters: longer first so "chairman" matches before "he" inside it doesn't,
        # and word boundaries prevent in-word substitutions ("the" stays "the").
        replacements = [
            ("chairman", "chairperson"),
            ("manpower", "workforce"),
            ("freshmen", "first-year students"),
            ("blacklist", "blocklist"),
            ("his", "their"),
            ("he", "they"),
        ]
        out = span
        for k, v in replacements:
            out = re.sub(rf"\b{re.escape(k)}\b", v, out, flags=re.IGNORECASE)
        return json.dumps({"rewrite": out, "preserves_meaning": True})

    def _ground(self, prompt: str, **kwargs: Any) -> str:
        citation = kwargs.get("citation", "")
        # Deterministic: empty / 'unverified' citations are ungrounded; otherwise grounded.
        if not citation or "unverified" in citation.lower():
            return json.dumps({"status": "ungrounded"})
        return json.dumps({"status": "grounded"})
