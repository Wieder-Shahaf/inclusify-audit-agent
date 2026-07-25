"""Deterministic mock LLM driving the v2 pipeline.

BUILD_PLAN §3: MockLLM is the offline keystone. It returns schema-valid outputs for
every call-site so the DocumentAuditor -> EvidenceInvestigator -> ReportConsolidator
pipeline runs end-to-end with no keys. The same prompt always yields the same
response — tests can assert on the trace.

Call-site routing (by 'task' kwarg):
- task="classify"    → flag/skip decision JSON for a span (also drives eval's baseline)
- task="rewrite"     → templated inclusive-rewrite JSON
- task="audit"       → v2 DocumentAuditor: per-window candidate list + hint verdicts
- task="investigate" → v2 EvidenceInvestigator: scripted corpus/live-search/finalize loop
- task="consolidate" → v2 ReportConsolidator: retract low-confidence + group patterns

Output is always JSON-stringifiable text so callers can `json.loads` it.
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
        if task == "rewrite":
            return self._rewrite(prompt, **kwargs)
        if task == "audit":
            return self._audit(prompt, **kwargs)
        if task == "investigate":
            return self._investigate(prompt, **kwargs)
        if task == "consolidate":
            return self._consolidate(prompt, **kwargs)
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

    def _audit(self, prompt: str, **kwargs: Any) -> str:
        """v2 DocumentAuditor script (BUILD_PLAN R4): scan `window_text` for the same
        `self._flag_words` `_classify` uses; one candidate per DISTINCT word found,
        quoting the bare matched word verbatim — `find_quote` verifies against the raw
        text downstream, so quoting the word alone is sufficient and simplest; no need
        to reconstruct a surrounding sentence for a deterministic offline script.
        """
        window_text = kwargs.get("window_text") or prompt
        gendered = {"chairman", "his", "he"}
        candidates = []
        for w in self._flag_words:
            m = re.search(rf"\b{re.escape(w)}\b", window_text, flags=re.IGNORECASE)
            if not m:
                continue
            candidates.append({
                "quote": m.group(),
                "category": "gendered" if w in gendered else "exclusionary",
                "reason": f"contains: {w}",
                "lexicon_backed": True,
            })
        flagged = {w.lower() for w in self._flag_words}
        hint_verdicts = [
            {"term": t, "verdict": "flag" if t.lower() in flagged else "clean"}
            for t in (kwargs.get("hint_terms") or [])
        ]
        return json.dumps({"candidates": candidates, "hint_verdicts": hint_verdicts})

    def _investigate(self, prompt: str, **kwargs: Any) -> str:
        """v2 EvidenceInvestigator script (BUILD_PLAN R5): scripted 2-4 turn tool loop,
        driven entirely by the `investigate()` call-site kwargs so it stays deterministic.

        Turn 1 always searches the corpus first. From turn 2: a literal "master" in
        the quote is always rejected as technical usage (the classic master/slave-in-a-
        benign-technical-sense regression case) regardless of evidence; otherwise
        strong corpus evidence (top_score >= 0.3) confirms right away; weak evidence
        escalates to live_search exactly once, at turn 2, when it's wired up; anything
        still weak after that finalizes low-confidence and flagged for human review
        rather than stalling.
        """
        turn = kwargs.get("turn", 1)
        quote = kwargs.get("candidate_quote") or ""
        category = kwargs.get("category") or "potentially-offensive"
        top_score = kwargs.get("top_score") or 0.0
        live_available = bool(kwargs.get("live_available", False))

        if turn == 1:
            words = " ".join(quote.split()[:6])
            return json.dumps({"action": "corpus_search", "query": f"{category}: {words}"})

        if "master" in quote.lower():
            return json.dumps({
                "action": "finalize", "verdict": "rejected", "category": category,
                "secondary_category": None, "explanation": "technical usage in context",
                "rewrite": "", "confidence": "medium", "needs_human_review": False,
                "evidence_used": [],
            })

        if top_score >= 0.3:
            rewrite = json.loads(self._rewrite(prompt, span=quote))["rewrite"]
            return json.dumps({
                "action": "finalize", "verdict": "confirmed", "category": category,
                "secondary_category": None,
                "explanation": "corroborated by retrieved corpus evidence [1]",
                "rewrite": rewrite,
                "confidence": "high" if top_score >= 0.5 else "medium",
                "needs_human_review": False, "evidence_used": [1],
            })

        if live_available and turn == 2:
            return json.dumps({
                "action": "live_search", "phrases": ["inclusive language"],
                "any_of": ["curriculum"], "min_year": 2010,
            })

        rewrite = json.loads(self._rewrite(prompt, span=quote))["rewrite"]
        return json.dumps({
            "action": "finalize", "verdict": "confirmed", "category": category,
            "secondary_category": None, "explanation": "weak evidence",
            "rewrite": rewrite, "confidence": "low", "needs_human_review": True,
            "evidence_used": [],
        })

    def _consolidate(self, prompt: str, **kwargs: Any) -> str:
        """v2 ReportConsolidator script (BUILD_PLAN R6): retract the FIRST
        confirmed finding with confidence=="low" (seeds the `retract` trace event
        offline), keep the rest; group kept findings into one pattern per category
        that has >= 2 of them; fixed deterministic summary.

        Driven entirely by the `findings` kwarg (the same compact list
        `consolidate.consolidate` builds and passes to the prompt), so this stays a
        pure function of that input like every other MockLLM script.
        """
        findings = kwargs.get("findings") or []
        retracted_id = None
        kept = []
        for f in findings:
            if retracted_id is None and f.get("confidence") == "low":
                retracted_id = f["id"]
                continue
            kept.append(f)
        retracted = (
            [{"id": retracted_id, "rationale": "weak grounding — likely false positive"}]
            if retracted_id else []
        )

        by_category: dict[str, list[str]] = {}
        for f in kept:
            by_category.setdefault(f["category"], []).append(f["id"])
        patterns = [
            {"framing": f"recurring {cat} phrasing", "category": cat, "finding_ids": ids}
            for cat, ids in by_category.items() if len(ids) >= 2
        ]

        return json.dumps({
            "kept": [f["id"] for f in kept],
            "retracted": retracted,
            "patterns": patterns,
            "summary": "Consolidation complete: findings reviewed for duplicates, "
                       "contradictions, and recurring patterns.",
        })
