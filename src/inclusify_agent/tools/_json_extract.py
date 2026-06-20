"""Robust JSON extraction from LLM output.

Live models often wrap JSON in markdown fences (```json ... ```) or surround it with
prose. This helper finds the first balanced JSON object/array in the string.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Return the first parseable JSON object/array in text, or raise json.JSONDecodeError.

    Tries in order:
    1. Whole string is JSON.
    2. JSON inside a ```json``` or ``` fenced block.
    3. First balanced { ... } substring (naive brace matching).
    """
    if not text:
        raise json.JSONDecodeError("empty input", "", 0)
    stripped = text.strip()
    # 1. Whole string.
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # 2. Fenced.
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. Brace-matched substring.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise json.JSONDecodeError("no JSON found in text", text, 0)
