"""Tests for the robust JSON extractor used to parse live LLM output."""
from __future__ import annotations

import json

import pytest

from inclusify_agent.tools._json_extract import extract_json


def test_extract_pure_json() -> None:
    assert extract_json('{"label": "flag"}') == {"label": "flag"}


def test_extract_array() -> None:
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_extract_from_fenced_block() -> None:
    text = 'Here is the result:\n```json\n{"label": "flag", "reason": "x"}\n```\nDone.'
    assert extract_json(text) == {"label": "flag", "reason": "x"}


def test_extract_from_unlabeled_fence() -> None:
    text = '```\n{"a": 1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_from_prose_with_braces() -> None:
    text = 'The classification is: {"label": "flag", "category": "gendered"}. That is all.'
    assert extract_json(text) == {"label": "flag", "category": "gendered"}


def test_extract_skips_unbalanced_braces() -> None:
    """If there's a bogus `{` before the real JSON, the extractor should keep trying."""
    text = '{this is not json. The actual object is {"label": "skip"}'
    assert extract_json(text) == {"label": "skip"}


def test_extract_raises_on_empty() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("")


def test_extract_raises_on_no_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json("just prose, no braces here")


def test_extract_handles_nested() -> None:
    text = 'Result: {"outer": {"inner": [1, 2, 3]}, "x": "y"}'
    assert extract_json(text) == {"outer": {"inner": [1, 2, 3]}, "x": "y"}
