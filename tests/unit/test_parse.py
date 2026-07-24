"""Unit tests for the v2 offset-exact parser (PRD §5, BUILD_PLAN R1)."""
from __future__ import annotations

import time

from inclusify_agent.tools import (
    Block,
    Sentence,
    Window,
    find_quote,
    is_probably_english,
    max_windows,
    parse,
)

# ---- synthetic fixtures --------------------------------------------------------

# Headings (numbered "1."/"2.1", ALL-CAPS), a bulleted list, and hard-wrapped
# (single-\n) paragraphs containing abbreviations — built as a list-of-blocks and
# joined with blank lines so the block boundaries are unambiguous.
_STRUCTURE_DOC = "\n\n".join([
    "1. Introduction",
    "This is the first paragraph about the course. It has multiple sentences.\n"
    "Dr. Smith wrote about this topic extensively, and et al. contributed too.",
    "GRADING POLICY",
    "- First bullet point here.\n"
    "- Second bullet point here.\n"
    "- Third bullet point here.",
    "2.1 Late Submissions",
    "Submissions after the deadline lose ten percent per day. See e.g. the\n"
    "syllabus for details on exceptions to this rule.",
])


def _filler_paragraph(word: str, n_words: int) -> str:
    return " ".join([word] * n_words) + "."


def _make_big_doc(n_paragraphs: int, words_per_paragraph: int) -> str:
    """A synthetic multi-paragraph doc sized purely by word count (content is filler)."""
    base = "The quick brown fox jumps over the lazy dog near the bank today.".split()
    reps = words_per_paragraph // len(base) + 1
    para_words = (base * reps)[:words_per_paragraph]
    paragraph = " ".join(para_words) + "."
    return "\n\n".join([paragraph] * n_paragraphs)


def _assert_roundtrip(raw: str, blocks: list[Block], sentences: list[Sentence],
                       windows: list[Window]) -> None:
    for b in blocks:
        assert raw[b.char_start:b.char_end] == b.text
    for s in sentences:
        assert raw[s.char_start:s.char_end] == s.text
        assert 0 <= s.block_idx < len(blocks)
        assert blocks[s.block_idx].kind in ("paragraph", "list")
    for w in windows:
        for idx in w.block_idxs:
            assert 0 <= idx < len(blocks)
            b = blocks[idx]
            assert raw[b.char_start:b.char_end] == b.text


# ---- 1. Block classification + offsets round-trip ------------------------------

def test_block_classification_headings_lists_paragraphs() -> None:
    blocks, sentences, windows = parse(_STRUCTURE_DOC)
    kinds = [b.kind for b in blocks]
    assert kinds == ["heading", "paragraph", "heading", "list", "heading", "paragraph"]
    _assert_roundtrip(_STRUCTURE_DOC, blocks, sentences, windows)


def test_hard_wrapped_paragraph_lines_not_unwrapped() -> None:
    blocks, _sentences, _windows = parse(_STRUCTURE_DOC)
    # Blocks 1 and 5 are the hard-wrapped paragraphs; their internal "\n" survives.
    assert "\n" in blocks[1].text
    assert "\n" in blocks[5].text


def test_numbered_and_allcaps_headings_recognized() -> None:
    blocks, _sentences, _windows = parse(_STRUCTURE_DOC)
    assert blocks[0].text == "1. Introduction"
    assert blocks[2].text == "GRADING POLICY"
    assert blocks[4].text == "2.1 Late Submissions"


def test_bullet_list_recognized() -> None:
    blocks, _sentences, _windows = parse(_STRUCTURE_DOC)
    assert blocks[3].kind == "list"
    assert blocks[3].text.count("\n") == 2  # 3 bullet lines


# ---- 2. Sentence segmentation / abbreviation guard ------------------------------

def test_abbreviation_guard_et_al_no_split() -> None:
    text = "The committee, et al. Smith found the results compelling."
    _blocks, sentences, _windows = parse(text)
    assert len(sentences) == 1
    assert sentences[0].text == text


def test_abbreviation_guard_eg_no_split() -> None:
    text = "Consider e.g. the results shown below for comparison purposes today."
    _blocks, sentences, _windows = parse(text)
    assert len(sentences) == 1
    assert sentences[0].text == text


def test_real_period_does_split() -> None:
    text = "The meeting reached its end. The next item was budget."
    _blocks, sentences, _windows = parse(text)
    assert len(sentences) == 2
    assert sentences[0].text == "The meeting reached its end."
    assert sentences[1].text == "The next item was budget."


def test_headings_are_not_sentence_segmented() -> None:
    blocks, sentences, _windows = parse(_STRUCTURE_DOC)
    heading_idxs = {i for i, b in enumerate(blocks) if b.kind == "heading"}
    assert not any(s.block_idx in heading_idxs for s in sentences)


# ---- 3. Window assembly: overlap ------------------------------------------------

def test_window_overlap_repeats_last_paragraph() -> None:
    p1 = _filler_paragraph("alpha", 100)
    p2 = _filler_paragraph("beta", 100)
    p3 = _filler_paragraph("gamma", 100)
    doc = f"{p1}\n\n{p2}\n\n{p3}"
    blocks, _sentences, windows = parse(doc, window_tokens=300)
    assert len(blocks) == 3
    assert len(windows) == 2
    w0, w1 = windows
    assert w0.block_idxs == [0, 1]
    # Window 1 repeats window 0's last paragraph (block idx 1) at its head.
    assert w1.block_idxs[0] == 1
    assert w1.char_start == blocks[1].char_start
    assert w1.overlap_char_end == blocks[1].char_end == w0.char_end
    assert w1.text.startswith(blocks[1].text)
    # A span inside the overlap resolves under BOTH windows' absolute offsets:
    # it's within w0's [char_start, char_end) and within w1's [char_start, overlap_char_end).
    span_start, span_end = blocks[1].char_start + 5, blocks[1].char_start + 10
    assert w0.char_start <= span_start and span_end <= w0.char_end
    assert w1.char_start <= span_start and span_end <= w1.overlap_char_end
    _assert_roundtrip(doc, blocks, _sentences, windows)


def test_first_window_has_no_overlap() -> None:
    doc = _filler_paragraph("solo", 50)
    blocks, _sentences, windows = parse(doc, window_tokens=300)
    assert len(windows) == 1
    assert windows[0].overlap_char_end == windows[0].char_start == blocks[0].char_start


# ---- 4. Oversized paragraph -> sentence-boundary fallback ----------------------

def test_oversized_paragraph_falls_back_to_sentence_windows() -> None:
    text = " ".join(f"Sentence number {i} is here." for i in range(60))
    blocks, sentences, windows = parse(text, window_tokens=50)
    assert len(blocks) == 1
    assert blocks[0].kind == "paragraph"
    assert len(sentences) == 60
    assert len(windows) > 1
    sentence_ends = {s.char_end for s in sentences}
    for w in windows:
        # Every window's own content ends exactly on a sentence boundary.
        assert w.char_end in sentence_ends
    _assert_roundtrip(text, blocks, sentences, windows)


# ---- 5. Windows on a large synthetic doc: sane count + budget -------------------

def test_windows_on_large_synthetic_doc_are_sane() -> None:
    doc = _make_big_doc(n_paragraphs=50, words_per_paragraph=230)  # ~11.5k words -> ~15k tokens
    blocks, sentences, windows = parse(doc)
    assert 7 <= len(windows) <= 12
    for w in windows:
        est_tokens = len(w.text.split()) * 1.3
        assert est_tokens <= 1800 * 1.3 + 1e-6
    _assert_roundtrip(doc, blocks, sentences, windows)


def test_parse_perf_sanity() -> None:
    doc = _make_big_doc(n_paragraphs=60, words_per_paragraph=230)  # ~75k chars
    assert len(doc) > 50_000
    start = time.perf_counter()
    parse(doc)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0  # loose: correctness, not a benchmark


# ---- 6. find_quote ---------------------------------------------------------------

def test_find_quote_exact_hit() -> None:
    raw = "The chairman will hold office hours weekly."
    quote = "chairman will hold"
    result = find_quote(raw, quote)
    assert result is not None
    start, end = result
    assert raw[start:end] == quote
    assert start == raw.index(quote)


def test_find_quote_whitespace_mangled_hard_wrap() -> None:
    raw = "Announcement: The chairman will hold extra office hours next week."
    mangled = "The  chairman\nwill  hold"
    result = find_quote(raw, mangled)
    assert result is not None
    start, end = result
    assert raw[start:end] == "The chairman will hold"


def test_find_quote_miss_returns_none() -> None:
    raw = "The chairman will hold office hours weekly."
    assert find_quote(raw, "this text does not appear anywhere") is None


def test_find_quote_respects_search_start() -> None:
    raw = "repeat repeat repeat"
    first = find_quote(raw, "repeat")
    assert first == (0, 6)
    second = find_quote(raw, "repeat", search_start=1)
    assert second == (7, 13)


# ---- 7. Guards ---------------------------------------------------------------

def test_is_probably_english_true_for_english() -> None:
    assert is_probably_english("The chairman will hold office hours weekly.") is True


def test_is_probably_english_false_for_hebrew() -> None:
    assert is_probably_english("שלום עולם, זהו טקסט בעברית בלבד ללא אנגלית כלל.") is False


def test_is_probably_english_false_for_empty_or_no_letters() -> None:
    assert is_probably_english("") is False
    assert is_probably_english("    ") is False
    assert is_probably_english("1234 !!! ...") is False


def test_max_windows_default_and_env(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_MAX_WINDOWS", raising=False)
    assert max_windows() == 40
    monkeypatch.setenv("AGENT_MAX_WINDOWS", "7")
    assert max_windows() == 7


# ---- 8. Empty input -------------------------------------------------------------

def test_parse_empty_text() -> None:
    assert parse("") == ([], [], [])
    assert parse("   \n\n  ") == ([], [], [])
