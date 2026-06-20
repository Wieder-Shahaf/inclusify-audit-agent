"""Unit tests for all 7 tools (BUILD_PLAN §6, P3 exit check)."""
from __future__ import annotations

import io

from inclusify_agent.providers.embeddings import HashEmbeddings
from inclusify_agent.providers.llm import MockLLM
from inclusify_agent.providers.vectorstore import InMemoryStore
from inclusify_agent.tools import (
    Chunk,
    Citation,
    Finding,
    LexiconHit,
    ask_user,
    chunk,
    classify_span,
    lexicon_lookup,
    load_lexicon,
    propose_rewrite,
    record_finding,
    retrieve_citation,
)

# ---- chunk -------------------------------------------------------------------

def test_chunk_splits_on_sentences() -> None:
    text = "The chairman approved. The committee met. Each student brought his laptop."
    out = chunk(text)
    assert len(out) == 3
    assert all(isinstance(c, Chunk) for c in out)
    assert out[0].text.startswith("The chairman")
    assert out[2].text.endswith("laptop.")


def test_chunk_captures_offsets() -> None:
    text = "Alpha sentence. Beta sentence."
    out = chunk(text)
    # The first chunk's text should match what its char range points at.
    assert text[out[0].char_start:out[0].char_end] == out[0].text


def test_chunk_carries_context() -> None:
    text = "Alpha. Beta. Gamma."
    out = chunk(text, context_chars=20)
    assert "Alpha" in out[1].context_before
    assert "Gamma" in out[1].context_after


def test_chunk_handles_empty() -> None:
    assert chunk("") == []
    assert chunk("   \n  ") == []


# ---- lexicon_lookup ----------------------------------------------------------

def test_lexicon_loads_bundled_data() -> None:
    entries = load_lexicon()
    assert len(entries) > 30  # retext-equality + Tiny Heap abridged set
    terms = {e["term"] for e in entries}
    assert "chairman" in terms
    assert "manpower" in terms
    assert "blacklist" in terms


def test_lexicon_lookup_finds_known_terms() -> None:
    c = Chunk(id="c0", text="The chairman approved the blacklist.", char_start=0, char_end=37)
    hits = lexicon_lookup(c)
    terms = {h.term for h in hits}
    assert "chairman" in terms
    assert "blacklist" in terms


def test_lexicon_lookup_is_case_insensitive() -> None:
    c = Chunk(id="c0", text="The CHAIRMAN spoke.", char_start=0, char_end=20)
    hits = lexicon_lookup(c)
    assert any(h.term == "chairman" for h in hits)


def test_lexicon_lookup_respects_word_boundaries() -> None:
    # "he" must NOT match "the"
    c = Chunk(id="c0", text="The committee approved.", char_start=0, char_end=24)
    hits = lexicon_lookup(c)
    assert not any(h.term == "he" for h in hits)


def test_lexicon_hit_carries_alternatives() -> None:
    c = Chunk(id="c0", text="The chairman left.", char_start=0, char_end=19)
    hits = lexicon_lookup(c)
    chairman = next(h for h in hits if h.term == "chairman")
    assert isinstance(chairman, LexiconHit)
    assert "chairperson" in chairman.alternatives


# ---- classify_span -----------------------------------------------------------

def test_classify_span_returns_schema_valid_dict() -> None:
    out = classify_span(MockLLM(), span="The chairman approved.")
    assert "label" in out
    assert "category" in out
    assert "reason" in out
    assert out["label"] in {"flag", "skip"}


def test_classify_span_flags_known_bias() -> None:
    out = classify_span(MockLLM(), span="The chairman approved.")
    assert out["label"] == "flag"


def test_classify_span_skips_clean() -> None:
    out = classify_span(MockLLM(), span="The committee approved.")
    assert out["label"] == "skip"


# ---- retrieve_citation -------------------------------------------------------

def test_retrieve_citation_returns_list_of_citations() -> None:
    emb = HashEmbeddings(dim=32)
    store = InMemoryStore(dim=32)
    store.add(
        ids=["d1", "d2"],
        vectors=emb.embed(["inclusive language in classrooms", "the eiffel tower"]),
        texts=["Inclusive language matters in education.", "Eiffel tower is in Paris."],
    )
    cites = retrieve_citation(store, emb, query="inclusive language", k=2)
    assert len(cites) <= 2
    assert all(isinstance(c, Citation) for c in cites)
    assert cites[0].text  # not empty


def test_retrieve_citation_empty_query_returns_empty() -> None:
    emb = HashEmbeddings(dim=32)
    store = InMemoryStore(dim=32)
    store.add(["d1"], emb.embed("x"), ["x"])
    assert retrieve_citation(store, emb, query="") == []


# ---- propose_rewrite ---------------------------------------------------------

def test_propose_rewrite_returns_rewrite_field() -> None:
    out = propose_rewrite(MockLLM(), span="The chairman approved.", category="gendered")
    assert "rewrite" in out
    assert "chairperson" in out["rewrite"]


def test_propose_rewrite_preserves_meaning_flag() -> None:
    out = propose_rewrite(MockLLM(), span="text", category=None)
    assert "preserves_meaning" in out


# ---- ask_user ----------------------------------------------------------------

def test_ask_user_auto_mode() -> None:
    out = ask_user("What did you mean?", mode="auto", default_answer="unknown")
    assert out["mode"] == "auto"
    assert out["question"] == "What did you mean?"
    assert out["answer"] == "unknown"


def test_ask_user_interactive_mode_reads_stdin() -> None:
    stdin = io.StringIO("clarification text\n")
    stdout = io.StringIO()
    out = ask_user("clarify?", mode="interactive", stdin=stdin, stdout=stdout)
    assert out["mode"] == "interactive"
    assert out["answer"] == "clarification text"
    assert "[ask_user]" in stdout.getvalue()


def test_ask_user_rejects_bad_mode() -> None:
    import pytest
    with pytest.raises(ValueError, match="mode"):
        ask_user("q", mode="nonsense")


# ---- record_finding ----------------------------------------------------------

def test_record_finding_appends_to_list() -> None:
    findings: list[Finding] = []
    f = Finding(id="f1", chunk_id="c0", span="chairman", label="flag",
                category="gendered", reason="trigger")
    out = record_finding(findings, f)
    assert out is findings  # mutates in place
    assert findings == [f]


def test_record_finding_preserves_order() -> None:
    findings: list[Finding] = []
    for i in range(3):
        record_finding(findings, Finding(
            id=f"f{i}", chunk_id="c0", span=f"s{i}",
            label="flag", category="gendered", reason="x",
        ))
    assert [f.id for f in findings] == ["f0", "f1", "f2"]
