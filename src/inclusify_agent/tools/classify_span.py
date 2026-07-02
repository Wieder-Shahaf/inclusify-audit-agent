"""Tool: LLM classification of a span (the escalation past lexicon)."""
from __future__ import annotations

import json
from typing import Any

from ._json_extract import extract_json

# The FLAG/SKIP examples below are drawn from the Achva expert review set
# (domain experts labeled course-material sentences; data/gold/achva/, local-only
# per the gitignore policy — 13 exemplars here, the rest is the held-out gold). The
# decisive doctrine they encode: flag a sentence whose SUBJECT is a harmful or
# debunked view — even hedged ('some argue', 'historically it was assumed') and
# even when the sentence calls it discredited — because restating the framing
# perpetuates it in course material. Skip only when the subject is the
# correction, affirmation, or respectful finding itself.
_SYSTEM = (
    "You are an inclusive-language auditor for academic writing (English and Hebrew). "
    "Be SENSITIVE to subtle bias but PRECISE about clean text.\n\n"
    "FLAG (label='flag') when the span contains any of these — even subtly:\n"
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
    "THE DECISIVE RULE: a sentence whose subject IS a harmful or debunked view gets "
    "flagged even when hedged ('some individuals perceive...', 'historically it was "
    "assumed...') and even when the sentence itself calls the view discredited — "
    "restating the framing perpetuates it in course material. SKIP (label='skip') "
    "only when the subject is the correction, the affirmation, or the respectful "
    "finding itself.\n\n"
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
    "altered through therapeutic interventions.' -> FLAG (biased — conversion-therapy "
    "framing of orientation as curable).\n"
    "- 'Bisexual individuals are frequently perceived as experiencing an interim "
    "period towards definitive heterosexuality.' -> FLAG (biased — bisexuality as a "
    "temporary phase).\n"
    "- 'The chairman approved the budget.' -> FLAG (gendered).\n"
    "- 'ההמלצות של WPATH מספקות הנחיות לטיפולים רפואיים בהקשר של דיספוריה מגדרית.' "
    "-> SKIP (current, professional medical framing).\n"
    "- 'חגיגות גאווה עלולות לעורר אי-נוחות בקרב חברי קהילה מסוימים.' -> FLAG "
    "(potentially-offensive — centers others' discomfort to cast Pride negatively).\n"
    "- 'טקסטים רפואיים היסטוריים השתמשו לעיתים קרובות במונח 'טרנסווסטיט'...' -> FLAG "
    "(outdated — reproduces the outdated term's framing even as historical reference).\n\n"
    "Use 'ask' ONLY when context truly determines the answer ('He arrived late' "
    "could refer to a named person).\n\n"
    "Respond with ONLY a JSON object, no prose, no markdown fences:\n"
    '{"label": "flag" | "ask" | "skip", '
    '"category": "gendered" | "exclusionary" | "ableist" | "outdated" | '
    '"factually-incorrect" | "potentially-offensive" | "biased" | null, '
    '"reason": "short explanation"}'
)


def classify_span(llm: Any, *, span: str, context: str = "") -> dict[str, Any]:
    """Ask the LLM to flag/skip a span. Returns a parsed JSON dict.

    Contract (BUILD_PLAN §3): the LLM (MockLLM or live) returns JSON with at minimum
    {"label": "flag"|"skip", "category": str|None, "reason": str}.
    """
    prompt = (
        f"span: {span!r}\n"
        f"context_before: {context!r}\n\n"
        "Return the classification JSON now."
    )
    raw = llm.complete(prompt=prompt, system=_SYSTEM, task="classify", span=span, context=context)
    try:
        result = extract_json(raw)
        if not isinstance(result, dict):
            raise json.JSONDecodeError("not a dict", raw, 0)
    except json.JSONDecodeError:
        return {"label": "skip", "category": None, "reason": "unparseable LLM output", "raw": raw}
    # Schema floor
    result.setdefault("label", "skip")
    result.setdefault("category", None)
    result.setdefault("reason", "")
    # Normalize label to known set.
    if result["label"] not in ("flag", "ask", "skip"):
        label_str = str(result.get("label", "")).lower()
        if label_str.startswith("flag"):
            result["label"] = "flag"
        elif label_str.startswith("ask"):
            result["label"] = "ask"
        else:
            result["label"] = "skip"
    return result
