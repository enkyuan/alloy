import pytest

from agentkit.knowledge.chunking import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("hello world", size=100, overlap=0) == ["hello world"]


def test_empty_text_yields_no_chunks():
    assert chunk_text("", size=100, overlap=0) == []


def test_whitespace_only_yields_no_chunks():
    assert chunk_text("   \n  ", size=100, overlap=0) == []


def test_long_text_splits_by_size():
    text = "a" * 250
    chunks = chunk_text(text, size=100, overlap=0)
    assert len(chunks) == 3
    assert chunks[0] == "a" * 100
    assert chunks[2] == "a" * 50


def test_overlap_repeats_tail():
    text = "abcdefghij"  # 10 chars
    chunks = chunk_text(text, size=5, overlap=2)
    # window slides by (size - overlap) = 3
    assert chunks[0] == "abcde"
    assert chunks[1] == "defgh"
    assert chunks[2] == "ghij"


def test_overlap_must_be_less_than_size():
    with pytest.raises(ValueError):
        chunk_text("abc", size=5, overlap=5)


def test_size_must_be_positive():
    with pytest.raises(ValueError):
        chunk_text("abc", size=0, overlap=0)


def test_unicode_text_is_preserved():
    chunks = chunk_text("café ☕ über", size=100, overlap=0)
    assert chunks == ["café ☕ über"]
