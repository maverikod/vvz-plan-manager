"""Deterministic long-text chunking and mean-pooling for SRT embedding.

A single embed request carries a bounded amount of text: the plan-level
own_text and expected_text of the root node (the reconstructed summary of the
whole plan, and the aggregated expected scope over every concept, relation, and
HRS paragraph) routinely exceed that bound, and the embedding service then
answers with no results ("embed-client response missing results"), which
degraded the root PLAN node of the Semantic Reproduction Tree.

This module resolves an over-long text by splitting it into chunks each within
a conservative character cap, embedding every chunk through the caller's
cache-first embed function, and returning the element-wise mean of the chunk
vectors as the text's vector. Short texts pass through unchanged (a single
embed call), so nothing changes for the vast majority of nodes.

The split is deterministic — it prefers paragraph ("\\n\\n") boundaries and
falls back to a hard character cut only when a single paragraph is itself over
the cap — so the same text always yields the same chunks, the same per-chunk
cache keys, and the same mean vector. Combined with the cache read-back in
:mod:`plan_manager.scoring.embedding`, the pooled root vector is stable across
runs and does not defeat snapshot deduplication.
"""

from __future__ import annotations

from typing import Callable


# The embedding service rejects (returns empty results for) a single text above
# a server-side size. 4000 characters is a conservative cap kept well under the
# observed failure threshold for one plan-level summary, chosen so a chunk is
# large enough to preserve local semantics yet always accepted by one embed
# request. Splitting is deterministic, so this constant only bounds chunk size;
# it does not otherwise affect the pooled vector.
SAFE_EMBED_CHARS = 4000


def split_text_for_embedding(text: str, cap: int = SAFE_EMBED_CHARS) -> list[str]:
    """Split ``text`` into chunks each at most ``cap`` characters, deterministically.

    A text at or under ``cap`` is returned as a single-element list unchanged.
    Otherwise the text is split on paragraph boundaries (``"\\n\\n"``) and
    paragraphs are greedily packed into chunks without exceeding ``cap``; any
    single paragraph longer than ``cap`` is hard-cut into ``cap``-sized slices.
    The paragraph separator is preserved between packed paragraphs so the
    reassembled chunks cover the original text.
    """
    if cap <= 0:
        raise ValueError("cap must be positive")
    if len(text) <= cap:
        return [text]

    # Each paragraph after the first carries its "\n\n" separator as a prefix,
    # so the pieces concatenate back to the exact original text and every chunk
    # is a run of whole pieces (or hard-cut slices of one over-long piece).
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for index, paragraph in enumerate(paragraphs):
        piece = paragraph if index == 0 else "\n\n" + paragraph
        if len(piece) > cap:
            # Flush what is buffered, then hard-cut the over-long piece.
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(piece), cap):
                chunks.append(piece[start : start + cap])
            continue
        if current and len(current) + len(piece) > cap:
            chunks.append(current)
            current = piece
        else:
            current += piece
    if current:
        chunks.append(current)
    return chunks


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Return the element-wise arithmetic mean of ``vectors``.

    All vectors must share the same dimension. Raises ``ValueError`` on an
    empty input or a dimension mismatch, so a degraded chunk can never be
    silently averaged into a shorter vector.
    """
    if not vectors:
        raise ValueError("cannot average an empty list of vectors")
    dim = len(vectors[0])
    for vector in vectors:
        if len(vector) != dim:
            raise ValueError("cannot average vectors of differing dimension")
    count = len(vectors)
    return [sum(vector[i] for vector in vectors) / count for i in range(dim)]


def embed_text_pooled(
    embed_one: Callable[[str], list[float]],
    text: str,
    cap: int = SAFE_EMBED_CHARS,
) -> list[float]:
    """Embed ``text`` through ``embed_one``, chunking and mean-pooling if long.

    ``embed_one`` resolves one within-cap text to its embedding vector
    (cache-first). When ``text`` fits in ``cap`` it is embedded directly, so
    the returned vector is exactly what ``embed_one`` would return. When it
    does not fit, each chunk from :func:`split_text_for_embedding` is embedded
    through ``embed_one`` and the element-wise :func:`mean_vector` of the chunk
    vectors is returned.
    """
    chunks = split_text_for_embedding(text, cap)
    if len(chunks) == 1:
        return embed_one(chunks[0])
    return mean_vector([embed_one(chunk) for chunk in chunks])
