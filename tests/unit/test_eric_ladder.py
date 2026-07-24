"""Unit tests for the ERIC search ladder (PRD v2.0 §6): compile_query + live_search_ladder.

compile_query is a pure function -> exact-string tests, no mocking. live_search_ladder hits
the network through urllib -> monkeypatch urllib.request.urlopen, same idiom as the existing
eric_live_search tests in test_tools.py. The live smoke test mirrors test_live_providers.py's
skipif convention: a module-level precomputed condition, skipped by default, opt-in via env.
"""
from __future__ import annotations

import io
import json
import urllib.request

import pytest

from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.tools import Citation
from inclusify_agent.tools.eric_live_search import (
    compile_query,
    eric_live_enabled,
    live_search_ladder,
)

# ---- compile_query (pure function) ---------------------------------------------

def test_compile_query_rung1_strict_with_year() -> None:
    q = compile_query(
        ["gendered language", "occupational titles"], ["curriculum", "syllabus"], 2015, 1,
    )
    assert q == (
        '"gendered language" AND "occupational titles" '
        'AND (curriculum OR curriculums OR syllabus) '
        'AND peerreviewed:T AND publicationdateyear:[2015 TO 2026]'
    )


def test_compile_query_rung1_no_min_year_omits_range() -> None:
    q = compile_query(["gendered language"], ["curriculum"], None, 1)
    assert q == '"gendered language" AND (curriculum OR curriculums) AND peerreviewed:T'


def test_compile_query_rung2_relaxed_drops_peerreviewed_and_year() -> None:
    q = compile_query(
        ["gendered language", "occupational titles"], ["curriculum", "syllabus"], 2015, 2,
    )
    assert q == (
        '"gendered language" AND "occupational titles" AND (curriculum OR curriculums OR syllabus)'
    )


def test_compile_query_rung2_with_no_any_of_omits_or_group() -> None:
    q = compile_query(["gendered language"], [], None, 2)
    assert q == '"gendered language"'


def test_compile_query_rung3_broad_is_unquoted_space_joined_words() -> None:
    q = compile_query(
        ["gendered language", "occupational titles"], ["curriculum", "syllabus"], 2015, 3,
    )
    assert q == "gendered language occupational titles curriculum syllabus"


def test_compile_query_strips_lucene_breaking_chars() -> None:
    q = compile_query(['gendered "titles"'], ["role:title"], None, 2)
    assert q == '"gendered titles" AND (roletitle OR roletitles)'


# ---- live_search_ladder (network mocked via urlopen) ---------------------------

class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):  # noqa: ANN002
        return False


def _payload(docs: list[dict]) -> _FakeResp:
    return _FakeResp(json.dumps({"response": {"docs": docs}}).encode())


def _doc(i: int, desc: object = None) -> dict:
    return {
        "id": f"EJ{i}",
        "title": f"Title {i}",
        "description": desc if desc is not None else f"description number {i} about bias",
        "publicationdateyear": 2020,
    }


def test_ladder_dormant_by_default_zero_network_calls(monkeypatch) -> None:
    """Offline-first: flag unset -> no network attempted at all, at any rung."""
    monkeypatch.delenv("ERIC_LIVE_SEARCH", raising=False)

    def _boom(*a, **kw):  # noqa: ANN002, ANN003
        raise AssertionError("network must not be touched when the flag is off")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert live_search_ladder(
        HashEmbeddings(dim=16), phrases=["inclusive language"], any_of=["curriculum"],
    ) == []


def test_ladder_stops_at_first_rung_with_enough_hits(monkeypatch) -> None:
    monkeypatch.setenv("ERIC_LIVE_SEARCH", "1")
    calls: list[str] = []

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls.append(req.full_url)
        if len(calls) == 1:
            return _payload([_doc(1)])  # rung 1: only 1 doc -> not enough, try rung 2
        return _payload([_doc(i) for i in range(2, 7)])  # rung 2: 5 docs -> enough, stop

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    cites = live_search_ladder(
        HashEmbeddings(dim=16),
        phrases=["inclusive language"],
        any_of=["curriculum"],
        min_year=2015,
        k=2,
    )
    assert len(calls) == 2, "must stop after rung 2, never trying rung 3"
    assert "peerreviewed%3AT" in calls[0] or "peerreviewed:T" in calls[0], "rung 1 request first"
    assert len(cites) == 2, "k must be respected"
    assert all(isinstance(c, Citation) for c in cites)
    assert all(c.metadata["rung"] == 2 for c in cites)
    assert cites[0].score >= cites[1].score, "must be cosine-sorted, best first"


def test_ladder_all_rungs_fail_network_returns_empty(monkeypatch) -> None:
    monkeypatch.setenv("ERIC_LIVE_SEARCH", "1")

    def _down(*a, **kw):  # noqa: ANN002, ANN003
        raise OSError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _down)
    assert live_search_ladder(
        HashEmbeddings(dim=16), phrases=["inclusive language"], any_of=["curriculum"],
    ) == []


def test_ladder_insufficient_hits_at_every_rung_returns_empty_bounded_requests(monkeypatch) -> None:
    monkeypatch.setenv("ERIC_LIVE_SEARCH", "1")
    calls: list[str] = []

    def _fake_urlopen(req, timeout=0):  # noqa: ANN001
        calls.append(req.full_url)
        return _payload([_doc(1)])  # always just 1 doc -> never enough, at any rung

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    assert live_search_ladder(HashEmbeddings(dim=16), phrases=["inclusive language"]) == []
    assert len(calls) == 3, "ladder is bounded to at most 3 requests (one per rung)"


def test_ladder_unescapes_html_and_filters_empty_descriptions(monkeypatch) -> None:
    monkeypatch.setenv("ERIC_LIVE_SEARCH", "1")
    docs = [
        {"id": "A", "title": "T&amp;A", "description": "bias &amp; stereotypes in curricula",
         "publicationdateyear": 2021},
        {"id": "B", "title": "Empty", "description": "", "publicationdateyear": 2021},
        {"id": "C", "title": "List desc", "description": ["part one", "part two"],
         "publicationdateyear": 2021},
        {"id": "D", "title": "Also fine", "description": "more curricula bias text here",
         "publicationdateyear": 2021},
    ]
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: _payload(docs))
    cites = live_search_ladder(
        HashEmbeddings(dim=16), phrases=["curricula bias"], any_of=["stereotypes"], k=3,
    )
    assert len(cites) == 3, "doc B has an empty description and must be dropped"
    assert all("&amp;" not in c.text for c in cites)
    assert {"T&A", "List desc", "Also fine"} == {c.metadata["title"] for c in cites}
    assert all(c.metadata["rung"] == 1 for c in cites)


# ---- LIVE smoke (opt-in; mirrors test_live_providers.py's skipif convention) ---

_LIVE = eric_live_enabled()


@pytest.mark.live
@pytest.mark.skipif(not _LIVE, reason="opt-in: set ERIC_LIVE_SEARCH=1 (network) to run")
def test_live_search_ladder_smoke() -> None:
    cites = live_search_ladder(
        HashEmbeddings(dim=16),
        phrases=["inclusive language"],
        any_of=["curriculum"],
        min_year=2015,
    )
    assert len(cites) >= 1
    assert cites[0].metadata["rung"] in (1, 2, 3)
    assert cites[0].metadata["url"].startswith("https://eric.ed.gov/?id=")
