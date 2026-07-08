"""Regression: the scoring batch must respect the embedding service's
maximum batch size, and surface a per-item failure precisely.

Bug BUG-PLANMGR-SCORING-EMBEDDING-UNREACHABLE-WHILE-HEALTH-READY-001 (root
cause): plan_manager sent every cache-miss text of a plan (64 for the live
doc-store plan) as one embed job, but the embedding service caps a job at 20
texts. Over the cap the service returned every result item with a null
embedding and a ``batch_limit_exceeded`` per-item error while the job still
"completed", so scoring degraded to "unreachable" for any plan with more than
a handful of unique texts — even though the single-call health probe reported
the model ready. The fix splits the array into sub-batches of at most
``MAX_EMBED_BATCH`` texts and stitches the vectors back together in order.
"""

import pytest

from plan_manager.scoring import embedding_batch
from plan_manager.scoring.embedding import EmbeddingUnavailable
from plan_manager.scoring.embedding_batch import MAX_EMBED_BATCH, fetch_vectors


class _RecordingClient:
    """Fake embed-client that records each sub-batch's size."""

    def __init__(self, calls: list[int]) -> None:
        self._calls = calls

    async def embed(self, texts, wait=False, error_policy=None):
        self._calls.append(len(texts))
        assert len(texts) <= MAX_EMBED_BATCH
        # Synchronous shape (no job_id) so wait_for_job is not exercised: one
        # deterministic 1-D vector per text, distinct per text length.
        return {"results": [{"embedding": [float(len(t))]} for t in texts]}

    async def close(self):
        return None


def test_fetch_vectors_splits_into_bounded_sub_batches(monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        embedding_batch, "_client_from_url",
        lambda base_url, timeout=60.0: _RecordingClient(calls),
    )

    texts = [f"text number {i} " + "x" * i for i in range(MAX_EMBED_BATCH * 2 + 3)]
    vectors = fetch_vectors("https://embed.example:8001", texts)

    # One embedding per text, aligned and in order.
    assert len(vectors) == len(texts)
    assert vectors == [[float(len(t))] for t in texts]
    # Split into ceil(N / MAX) sub-batches, none larger than the server cap.
    assert len(calls) == 3
    assert calls == [MAX_EMBED_BATCH, MAX_EMBED_BATCH, 3]
    assert all(size <= MAX_EMBED_BATCH for size in calls)


class _OverCapClient:
    """Fake service that rejects the whole job with a per-item error, as the
    real service does when the batch exceeds its maximum size."""

    async def embed(self, texts, wait=False, error_policy=None):
        return {
            "results": [
                {
                    "embedding": None,
                    "error": {
                        "code": "batch_limit_exceeded",
                        "message": "Batch size exceeds the maximum allowed (20)",
                    },
                }
                for _ in texts
            ]
        }

    async def close(self):
        return None


def test_fetch_vectors_surfaces_per_item_error(monkeypatch) -> None:
    monkeypatch.setattr(
        embedding_batch, "_client_from_url",
        lambda base_url, timeout=60.0: _OverCapClient(),
    )

    with pytest.raises(EmbeddingUnavailable, match="batch_limit_exceeded"):
        fetch_vectors("https://embed.example:8001", ["a", "b"])
