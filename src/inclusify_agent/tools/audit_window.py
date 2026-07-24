"""Tool: the v2 DocumentAuditor LLM call over one window (PRD §4 [2], BUILD_PLAN R4).

Per window: read the window text plus lexicon SENSOR HINTS pinned to it, return every
problematic span found (verbatim-verified later, in `pipeline.audit_document`) plus a
mandatory verdict for every hinted term — the lexicon never auto-flags on its own; the
Auditor adjudicates each hint in context (PRD §7's false-positive-pressure argument for
why a ≥1,500-term lexicon must stay a sensor, not a flagger).
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ._json_extract import extract_json
from .schemas import LexiconHit, Window

# The 7 canonical categories (PRD §1). Unknown/mismatched LLM output normalizes to the
# nearest of these (lowercase + hyphen/underscore -> space match) or falls back to
# "potentially-offensive".
_CATEGORIES = (
    "gendered", "exclusionary", "ableist", "outdated",
    "factually-incorrect", "potentially-offensive", "biased",
)
_CATEGORY_BY_KEY = {c.replace("-", " "): c for c in _CATEGORIES}

_CONDITION_PREFIX = "condition: "
_HINT_CAP = 20  # PRD §4 [2]: 143 hits measured on a real 12-page paper; cap the prompt.

# Adapted from classify_span._SYSTEM: same doctrine + FLAG/SKIP exemplars, English-only
# (the 3 Hebrew exemplars dropped — PRD §1's English-only scope), retargeted from
# "judge one given span" to "find every problematic span in this window" plus the
# hint-adjudication and structured-candidate-list contract v2 needs. ONE constant,
# byte-identical across every window/call in the whole run (and across runs) so a
# provider's KV-cache can reuse it (PRD §8) — all variable content (window text,
# heading path, hints) lives in the user prompt built by `_user_prompt`, never here.
_SYSTEM = (
    "You are an inclusive-language auditor for English academic writing (papers, "
    "syllabi, slides, guidelines). Be SENSITIVE to subtle bias but PRECISE about "
    "clean text.\n\n"
    "You are given a WINDOW — a few consecutive paragraphs of a larger document, "
    "with its section heading path if any — plus SENSOR HINTS: lexicon terms a "
    "deterministic first pass matched somewhere in this window. The lexicon is a "
    "sensor, never an auto-flagger: read every hinted term in its actual sentence "
    "and decide flag or clean yourself. Do not stop at the hints — also hunt the "
    "rest of the window for problems with no trigger word at all (implied bias, "
    "stereotyped framing, outdated claims). Dense academic text often contains "
    "SEVERAL problematic spans per window — enumerate every one you find, "
    "including repeated framings each time they carry the problem; do not stop "
    "at the most salient.\n\n"
    "FLAG a span when it contains any of these — even subtly:\n"
    "  - Gendered defaults: 'chairman', 'mankind', generic 'he/his', 'freshmen'.\n"
    "  - Exclusionary metaphors: 'blacklist', 'master/slave', 'sanity check'.\n"
    "  - Ableist terms: 'lame', 'crazy', 'cripple', 'tone-deaf'.\n"
    "  - Outdated identity terminology or framings: 'homosexuals' (as noun), "
    "'transgendered', 'sexual preference' (vs orientation), 'transvestite', "
    "framing identity as 'lifestyle'.\n"
    "  - Factually-incorrect claims about identity groups: oversimplifications, "
    "monolithic generalizations, debunked stereotypes.\n"
    "  - Potentially-offensive framings: phrasings that delegitimize inclusive "
    "practices or center disapproval/discomfort with a group.\n"
    "  - Biased framings: identity as mutable/curable, a 'phase', a threat to "
    "tradition or social stability.\n\n"
    "THE DECISIVE RULE: a sentence whose SUBJECT is a harmful or debunked view gets "
    "flagged even when hedged ('some individuals perceive...', 'historically it was "
    "assumed...') and even when the sentence itself calls the view discredited — "
    "restating the framing perpetuates it in course material. This applies equally "
    "to STUDY-REPORTING sentences: a sentence neutrally reporting a study, method, "
    "or finding whose premise is a discredited framing (e.g., inferring identity "
    "from appearance or physiology, pathologizing an identity) gets flagged — "
    "reporting the premise still restates it. SKIP a sentence when its subject is "
    "the correction, the affirmation, or the respectful finding itself.\n\n"
    "Expert-labeled examples:\n"
    "- 'In 1990, the World Health Organization reclassified homosexuality from a "
    "condition requiring treatment to a sexual orientation category...' -> SKIP "
    "(the subject is the corrective reclassification itself; accurate, affirming).\n"
    "- 'Family acceptance is a crucial dimension in the sociological study of the "
    "psychological well-being of LGBTQ+ adolescents.' -> SKIP (respectful, accurate "
    "scholarly framing).\n"
    "- 'Some individuals perceive the LGBTQ+ advocacy efforts as straying beyond "
    "reasonable bounds.' -> FLAG (potentially-offensive — hedged framing of advocacy "
    "as excessive; implied disapproval without explicit language).\n"
    "- 'In discussions of sexual fluidity, it is often assumed that bisexuality is "
    "merely a construct of individual belief rather than a discrete orientation.' -> "
    "FLAG (potentially-offensive — recasts bisexuality as subjective belief).\n"
    "- 'Historical psychiatric literature often posited that homosexual identities "
    "indicated underlying mental health concerns...' -> FLAG (outdated — restates "
    "the pathologizing framing; the discredited view is the subject).\n"
    "- 'Historically, effeminacy in boys has been viewed as an indicator of future "
    "homosexuality, a perspective that has since been discredited...' -> FLAG "
    "(outdated — perpetuates the stereotype even while calling it discredited).\n"
    "- 'The LGBTQ+ community is a monolithic group with uniform political goals...' "
    "-> FLAG (factually-incorrect — monolithic generalization).\n"
    "- ''Coming out' is often viewed as a marker of psychological instability.' -> "
    "FLAG (factually-incorrect — frames coming out as instability).\n"
    "- 'Sexual orientation is perceived as a mutable characteristic that may be "
    "altered through therapeutic interventions.' -> FLAG (biased — conversion-"
    "therapy framing of orientation as curable).\n"
    "- 'Bisexual individuals are frequently perceived as experiencing an interim "
    "period towards definitive heterosexuality.' -> FLAG (biased — bisexuality as "
    "a temporary phase).\n"
    "- 'Early studies measured participants' skull dimensions to identify criminal "
    "tendencies, reporting high classification accuracy.' -> FLAG (outdated — "
    "neutrally reports a physiognomic method; the discredited premise is the "
    "subject).\n"
    "- 'The model was trained to predict participants' sexual orientation from "
    "voice recordings, achieving strong accuracy.' -> FLAG (potentially-offensive "
    "— operationalizes the assumption that identity is inferable from biology/"
    "appearance).\n"
    "- 'The chairman approved the budget.' -> FLAG (gendered).\n\n"
    "Quote every flagged span EXACTLY verbatim from the window text — character-"
    "for-character, no paraphrasing, no ellipsis, no added or removed punctuation; "
    "an unverifiable quote is discarded downstream.\n\n"
    "Categories (use exactly one of these 7 per candidate): gendered | exclusionary "
    "| ableist | outdated | factually-incorrect | potentially-offensive | biased. "
    "Use factually-incorrect ONLY for verifiably false claims stated as fact; a "
    "discredited framing or premise is outdated (or biased), not "
    "factually-incorrect.\n\n"
    "You MUST return exactly one verdict per hinted term listed in the HINTS block "
    "below, even for terms you judge clean or don't otherwise mention.\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences, in exactly this "
    "shape:\n"
    '{"candidates": [{"quote": "...", "category": "...", "reason": "...", '
    '"lexicon_backed": true|false}], '
    '"hint_verdicts": [{"term": "...", "verdict": "flag"|"clean"}]}'
)


def _extract_condition(note: str) -> str:
    """Pull the "condition: ...;" prefix `lexicon_lookup._note_with_condition` folds
    into `LexiconHit.note`, if present; "" when the term carries no condition."""
    if not note.startswith(_CONDITION_PREFIX):
        return ""
    condition, _sep, _rest = note[len(_CONDITION_PREFIX):].partition("; ")
    return condition


def build_hints(hits: list[LexiconHit], window: Window) -> list[dict[str, Any]]:
    """Aggregate whole-document lexicon hits into this window's hint list (PRD §4 [2]).

    Grouped by DISTINCT term, not per-occurrence — a real 12-page paper measured 143
    hits; per-occurrence hints would bloat every prompt. Ordered rarest-first by the
    term's count across the WHOLE document (`hits` is the whole-doc `scan_document()`
    output): a term hit 64 times overall, e.g. generic "men", is the least locally
    informative one and sinks to the end even if this window only has one occurrence
    of it. Capped at 20 distinct terms per window.
    """
    doc_counts = Counter(h.term for h in hits)
    by_term: dict[str, list[LexiconHit]] = {}
    for h in hits:
        if window.char_start <= h.char_start < window.char_end:
            by_term.setdefault(h.term, []).append(h)

    ordered_terms = sorted(by_term, key=lambda t: doc_counts[t])
    hints = []
    for term in ordered_terms[:_HINT_CAP]:
        group = by_term[term]
        first = group[0]
        hints.append({
            "term": term,
            "category": first.category,
            "count": len(group),
            "sample_offsets": [(h.char_start, h.char_end) for h in group[:3]],
            "alternatives": list(first.alternatives[:3]),
            "condition": _extract_condition(first.note),
        })
    return hints


def _user_prompt(window: Window, hints: list[dict[str, Any]]) -> str:
    lines = []
    if window.heading_path:
        lines.append(f"Section: {window.heading_path}")
    lines.append("WINDOW TEXT:")
    lines.append(window.text)
    lines.append("")
    if hints:
        lines.append(
            "HINTS (lexicon sensor — adjudicate every one below, flag or clean; "
            "category/alternatives/condition are the lexicon entry's, not a verdict):"
        )
        for h in hints:
            alts = ", ".join(h["alternatives"]) if h["alternatives"] else "none"
            cond = f"; condition: {h['condition']}" if h["condition"] else ""
            lines.append(
                f'- "{h["term"]}" (category: {h["category"]}, count in window: '
                f'{h["count"]}, alternatives: {alts}{cond})'
            )
    else:
        lines.append("HINTS: none in this window.")
    lines.append("")
    lines.append(
        "Return ONLY the JSON object per the contract — "
        '{"candidates": [...], "hint_verdicts": [...]} — with exactly one '
        "hint_verdicts entry per hinted term above."
    )
    return "\n".join(lines)


def _normalize_category(raw: Any) -> str:
    if not raw:
        return "potentially-offensive"
    key = str(raw).strip().lower().replace("_", " ").replace("-", " ")
    return _CATEGORY_BY_KEY.get(key, "potentially-offensive")


def _try_parse(raw: str) -> dict[str, Any] | None:
    try:
        result = extract_json(raw)
    except json.JSONDecodeError:
        return None
    return result if isinstance(result, dict) else None


def _normalize(parsed: dict[str, Any], hint_terms: list[str]) -> dict[str, Any]:
    candidates = []
    for c in parsed.get("candidates") or []:
        if not isinstance(c, dict) or not c.get("quote"):
            continue
        candidates.append({
            "quote": c["quote"],
            "category": _normalize_category(c.get("category")),
            "reason": c.get("reason", ""),
            "lexicon_backed": bool(c.get("lexicon_backed", False)),
        })

    verdict_by_term: dict[str, str] = {}
    for v in parsed.get("hint_verdicts") or []:
        if not isinstance(v, dict) or not v.get("term"):
            continue
        verdict = v.get("verdict")
        verdict_by_term[v["term"]] = verdict if verdict in ("flag", "clean") else "clean"

    verdicts_filled = False
    hint_verdicts = []
    for term in hint_terms:
        if term in verdict_by_term:
            hint_verdicts.append({"term": term, "verdict": verdict_by_term[term]})
        else:
            hint_verdicts.append({"term": term, "verdict": "clean"})
            verdicts_filled = True

    return {
        "candidates": candidates,
        "hint_verdicts": hint_verdicts,
        "verdicts_filled": verdicts_filled,
    }


def audit_window(llm: Any, window: Window, hints: list[dict[str, Any]]) -> dict[str, Any]:
    """One DocumentAuditor call over `window` (PRD §4 [2], BUILD_PLAN R4).

    Always returns ``{"candidates": [...], "hint_verdicts": [...], "verdicts_filled":
    bool}`` — never raises. A JSON parse failure retries once with a sterner reminder
    appended; a second failure returns the empty/all-clean fallback below instead
    (``"parse_failed": True``) so a bad window never breaks the whole document run.
    """
    hint_terms = [h["term"] for h in hints]
    prompt = _user_prompt(window, hints)
    # 4000: a dense window's response can carry 20 hint_verdicts plus several
    # candidates each quoting a full sentence verbatim -- the 512 provider default
    # truncates that mid-JSON, which then "fails" the exact same way on the retry
    # (same cap) and silently degrades to empty candidates (see parse_failed below).
    call_kwargs = {"system": _SYSTEM, "task": "audit", "window_text": window.text,
                    "hint_terms": hint_terms, "max_tokens": 4000}

    raw = llm.complete(prompt, **call_kwargs)
    parsed = _try_parse(raw)
    if parsed is None:
        retry_prompt = prompt + "\n\nReturn ONLY the JSON object, no prose."
        raw = llm.complete(retry_prompt, **call_kwargs)
        parsed = _try_parse(raw)
    if parsed is None:
        return {
            "candidates": [],
            "hint_verdicts": [{"term": t, "verdict": "clean"} for t in hint_terms],
            "parse_failed": True,
        }
    return _normalize(parsed, hint_terms)
