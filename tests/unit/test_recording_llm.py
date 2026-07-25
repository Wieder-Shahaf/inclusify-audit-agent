"""Unit tests for RecordingLLM's response parsing — steps[].response must stay
structured (the spec's step sketch shows an object, not a string) while remaining
faithful to what the model actually emitted."""
from __future__ import annotations

from inclusify_agent.server.recording_llm import _as_obj


def test_as_obj_single_json_object() -> None:
    assert _as_obj('{"a": 1}') == {"a": 1}


def test_as_obj_concatenated_objects_become_list() -> None:
    assert _as_obj('{"a": 1}\n{"b": 2}') == [{"a": 1}, {"b": 2}]
    assert _as_obj('{"a": 1} {"b": 2} {"c": 3}') == [{"a": 1}, {"b": 2}, {"c": 3}]


def test_as_obj_non_json_tail_keeps_raw_string() -> None:
    raw = '{"a": 1} and then some prose'
    assert _as_obj(raw) == raw


def test_as_obj_plain_text_stays_string() -> None:
    assert _as_obj("not json at all") == "not json at all"
    assert _as_obj("") == ""
