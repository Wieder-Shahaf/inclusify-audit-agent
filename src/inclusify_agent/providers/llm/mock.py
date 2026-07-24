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
- task="audit"      → v2 DocumentAuditor: per-window candidate list + hint verdicts
- task="investigate" → v2 EvidenceInvestigator: scripted corpus/live-search/finalize loop

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
        if task == "audit":
            return self._audit(prompt, **kwargs)
        if task == "investigate":
            return self._investigate(prompt, **kwargs)
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
        """Pick next tool given the last action in the state hint.

        Scripted ReAct: lexicon_lookup → classify_span → retrieve_citation
        → propose_rewrite → (back to lexicon_lookup for next chunk) → ... → reflect.
        Deterministic; same hint always yields same tool.
        """
        hint = kwargs.get("state_hint", "")
        # state_hint format: "chunk_idx=I/N; last_action=X; findings=K"
        last_action = "lexicon_lookup"
        for part in hint.split(";"):
            part = part.strip()
            if part.startswith("last_action="):
                last_action = part.split("=", 1)[1]
        next_map = {
            "lexicon_lookup": "classify_span",
            "classify_span": "retrieve_citation",
            "retrieve_citation": "propose_rewrite",
            "propose_rewrite": "lexicon_lookup",   # next chunk's first action
            "ask_user": "lexicon_lookup",
            "reflect": "stop",
        }
        nxt = next_map.get(last_action, "lexicon_lookup")
        return json.dumps({"tool": nxt, "rationale": f"after {last_action}: {nxt}"})

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
