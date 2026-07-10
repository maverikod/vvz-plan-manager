"""Tests (F3): deterministic long-text chunking and mean-pooling.

The plan-level own_text and expected_text of the SRT root routinely exceed a
single embed request's size, so the service answered with no results and the
root PLAN node degraded. The chunk-and-mean helper splits an over-long text
deterministically, embeds each chunk cache-first, and returns the element-wise
mean, so the root carries a real vector instead of degrading.
"""

import pytest

from plan_manager.scoring.embedding_chunk import (
    SAFE_EMBED_CHARS,
    embed_text_pooled,
    mean_vector,
    split_text_for_embedding,
)


def test_short_text_is_a_single_chunk() -> None:
    text = "short paragraph"
    assert split_text_for_embedding(text) == [text]


def test_text_exactly_at_cap_is_a_single_chunk() -> None:
    text = "x" * SAFE_EMBED_CHARS
    assert split_text_for_embedding(text) == [text]


def test_long_text_splits_on_paragraph_boundaries_under_cap() -> None:
    para = "y" * 100
    text = "\n\n".join([para] * 80)  # 80 * 100 + separators > cap
    chunks = split_text_for_embedding(text, cap=1000)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    # The chunks reassemble to the exact original text (separators preserved).
    assert "".join(chunks) == text
    # Every chunk breaks on a paragraph boundary (no chunk splits a paragraph).
    for chunk in chunks:
        assert "y" * 100 in chunk or chunk.strip("\n") == ""


def test_single_oversized_paragraph_is_hard_cut() -> None:
    text = "z" * (SAFE_EMBED_CHARS * 2 + 37)
    chunks = split_text_for_embedding(text)

    assert len(chunks) == 3
    assert all(len(chunk) <= SAFE_EMBED_CHARS for chunk in chunks)
    assert "".join(chunks) == text


def test_split_is_deterministic() -> None:
    para = "word " * 60
    text = "\n\n".join([para] * 50)
    assert split_text_for_embedding(text, cap=800) == split_text_for_embedding(text, cap=800)


def test_mean_vector_is_element_wise_mean() -> None:
    assert mean_vector([[1.0, 2.0], [3.0, 4.0]]) == [2.0, 3.0]


def test_mean_vector_rejects_empty() -> None:
    with pytest.raises(ValueError):
        mean_vector([])


def test_mean_vector_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        mean_vector([[1.0, 2.0], [3.0]])


def test_pooled_short_text_passes_through_single_call() -> None:
    calls: list[str] = []

    def embed_one(chunk: str) -> list[float]:
        calls.append(chunk)
        return [float(len(chunk))]

    result = embed_text_pooled(embed_one, "short")
    assert result == [5.0]
    assert calls == ["short"]  # exactly one embed, no pooling


def test_pooled_long_text_means_chunk_vectors() -> None:
    # cap=6 forces one chunk per paragraph; each embed returns a constant known
    # vector so the mean is exact and checkable.
    text = "\n\n".join(["aaaa", "bbbb", "cccc"])
    vectors = {"aaaa": [3.0, 0.0], "\n\nbbbb": [0.0, 3.0], "\n\ncccc": [3.0, 3.0]}

    def embed_one(chunk: str) -> list[float]:
        return vectors[chunk]

    result = embed_text_pooled(embed_one, text, cap=6)
    # mean of the three chunk vectors, element-wise.
    assert result == [2.0, 2.0]
