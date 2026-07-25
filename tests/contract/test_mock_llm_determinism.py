"""MockLLM must be deterministic.

Critical for BUILD_PLAN §3: e2e tests assert structural invariants on the trace —
the trace stays stable across runs only if MockLLM's outputs are deterministic.
"""
from __future__ import annotations

import json

from inclusify_agent.providers.llm import MockLLM


def test_classify_is_deterministic() -> None:
    llm = MockLLM()
    a = llm.complete("Each student should bring his own laptop", task="classify",
                     span="Each student should bring his own laptop")
    b = llm.complete("Each student should bring his own laptop", task="classify",
                     span="Each student should bring his own laptop")
    assert a == b
    decoded = json.loads(a)
    assert decoded["label"] in {"flag", "skip"}


def test_classify_flags_known_bias() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="classify", span="The chairman approved it."))
    assert out["label"] == "flag"
    assert out["category"] == "gendered"
    assert "chairman" in out["reason"]


def test_classify_skips_clean_text() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="classify", span="The committee approved it."))
    assert out["label"] == "skip"


def test_rewrite_replaces_known_terms() -> None:
    llm = MockLLM()
    out = json.loads(llm.complete("", task="rewrite", span="The chairman approved his report."))
    assert "chairperson" in out["rewrite"]
    assert "their" in out["rewrite"]
