"""Batch embedding layer and model-readiness probe (C-013 scoring efficiency).

Resolves many texts against the pgvector cache in one round trip and
vectorizes only the cache misses through a single queued embedding batch,
replacing the per-text embed loop that issued one queued job per phrase and
blocked the scoring job for O(branches) sequential round trips. Also exposes
the embedding model readiness probe used by the scoring preflight and the
info/health surfaces, which separates a transport-reachable service from an
initialized model.

Builds on the primitives in :mod:`plan_manager.scoring.embedding`.
"""

import contextlib
import json
import uuid
import asyncio
from datetime import datetime, timezone

from embed_client.exceptions import EmbedClientError, EmbedError
import psycopg

from plan_manager.scoring.embedding import (
    EmbeddingUnavailable,
    READINESS_NOT_READY,
    READINESS_READY,
    READINESS_UNCONFIGURED,
    READINESS_UNREACHABLE,
    _client_from_url,
    _run_async_blocking,
    text_content_hash,
)


# The embedding service rejects an embed request whose text array is larger
# than a fixed server-side maximum (observed limit: 20 texts per job; over it
# every result item comes back with a null embedding and a ``batch_limit_
# exceeded`` / ``encode_error`` per-item error, while the job itself still
# "completes"). A whole plan routinely needs far more than that vectorized in
# one scoring pass, so the cache-miss array is split into sub-batches of at
# most this many texts, each submitted as its own queued job, and the vectors
# are stitched back together in order. Kept safely under the observed 20 so a
# tightened server limit does not silently break scoring again.
MAX_EMBED_BATCH = 16


def get_cached_vectors(
    conn: psycopg.Connection, texts: list[str]
) -> dict[str, list[float]]:
    """Return the cached vectors for ``texts`` in one indexed lookup.

    Issues a single ``WHERE content_hash = ANY(%s)`` query against
    ``embedding_cache`` (the pgvector-backed cache) instead of one query per
    text. Duplicate input texts collapse to one content hash. Texts without a
    cached vector are absent from the returned mapping.
    """
    if not texts:
        return {}
    hash_to_text: dict[str, str] = {}
    for text in texts:
        hash_to_text.setdefault(text_content_hash(text), text)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT content_hash, vector::text FROM embedding_cache "
            "WHERE content_hash = ANY(%s)",
            (list(hash_to_text.keys()),),
        )
        rows = cur.fetchall()
    out: dict[str, list[float]] = {}
    for content_hash_value, vector_text in rows:
        out[hash_to_text[content_hash_value]] = json.loads(vector_text)
    return out


def store_vectors(
    conn: psycopg.Connection, mapping: dict[str, list[float]]
) -> None:
    """Store many embedding vectors in the cache in one ``executemany``.

    Each row is keyed by the content hash of the text; on a content-hash
    conflict the insert is a no-op (``ON CONFLICT (content_hash) DO NOTHING``).
    """
    if not mapping:
        return
    rows = [
        (
            uuid.uuid4(),
            text_content_hash(text),
            json.dumps(vector),
            datetime.now(timezone.utc),
        )
        for text, vector in mapping.items()
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO embedding_cache (uuid, content_hash, vector, created_at) "
            "VALUES (%s, %s, %s::vector, %s) "
            "ON CONFLICT (content_hash) DO NOTHING",
            rows,
        )


def _extract_chunk_vectors(
    results: object, chunk: list[str]
) -> list[list[float]]:
    """Validate one sub-batch response and return its vectors in order.

    Raises ``EmbeddingUnavailable`` with a precise reason when the response is
    malformed or an item carries no vector — surfacing the service's per-item
    ``error`` (e.g. ``batch_limit_exceeded``) instead of a generic message, so
    the real failure reaches the scoring diagnostic rather than being hidden
    behind "missing embedding list".
    """
    if not isinstance(results, list) or len(results) != len(chunk):
        raise EmbeddingUnavailable(
            "embed batch returned a results list that does not match the "
            "number of requested texts"
        )
    vectors: list[list[float]] = []
    for item in results:
        if not isinstance(item, dict):
            raise EmbeddingUnavailable("embed batch result item is not an object")
        embedding = item.get("embedding")
        if not isinstance(embedding, list):
            item_error = item.get("error")
            if item_error:
                raise EmbeddingUnavailable(
                    f"embed batch result item has no embedding vector: {item_error}"
                )
            raise EmbeddingUnavailable("embed batch result item missing embedding list")
        vectors.append(embedding)
    return vectors


async def _fetch_vectors_async(
    base_url: str, texts: list[str], timeout: float
) -> list[list[float]]:
    client = _client_from_url(base_url, timeout=timeout)
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), MAX_EMBED_BATCH):
            chunk = texts[start : start + MAX_EMBED_BATCH]
            submitted = await client.embed(chunk, wait=False, error_policy="fail_fast")
            job_id = submitted.get("job_id")
            if job_id:
                completed = await client.wait_for_job(job_id, timeout=timeout)
                results = completed.get("results")
            else:
                results = submitted.get("results")
            vectors.extend(_extract_chunk_vectors(results, chunk))
    finally:
        with contextlib.suppress(Exception):
            await client.close()
    return vectors


def fetch_vectors(
    base_url: str, texts: list[str], timeout: float = 60.0
) -> list[list[float]]:
    """Vectorize a whole array of texts through queued embedding sub-batches.

    Each sub-batch of at most :data:`MAX_EMBED_BATCH` texts is submitted with
    ``wait=False`` so it runs through the embedding service queue and its job
    can be observed, per the queue-only vectorization contract, honoring the
    server-side maximum batch size. Every sub-batch job is bounded by
    ``max(timeout, 60.0)`` and the sub-batches run in order over one client
    session; the vectors are returned aligned one-to-one to ``texts``.

    Raises
    ------
    EmbeddingUnavailable
        When the batch cannot be reached, a job fails or times out, or the
        response does not carry one embedding per requested text.
    """
    if not texts:
        return []
    batch_timeout = max(timeout, 60.0)
    n_chunks = (len(texts) + MAX_EMBED_BATCH - 1) // MAX_EMBED_BATCH
    try:
        return _run_async_blocking(
            _fetch_vectors_async(base_url, texts, batch_timeout),
            timeout=batch_timeout * n_chunks + 5.0,
        )
    except (
        asyncio.TimeoutError,
        EmbedClientError,
        EmbedError,
        TimeoutError,
        OSError,
        RuntimeError,
    ) as exc:
        raise EmbeddingUnavailable(str(exc)) from exc


def embed_texts(
    conn: psycopg.Connection,
    base_url: str,
    texts: list[str],
    timeout: float = 60.0,
    progress=None,
) -> dict[str, list[float]]:
    """Return vectors for every text in ``texts``, cache-first and batched.

    Resolves all unique texts against the pgvector cache in one query, sends
    only the cache misses to the embedding service as a single queued batch,
    stores the fetched vectors in one write, and returns the full mapping.

    Parameters
    ----------
    progress:
        Optional callable ``progress(pct=None, message=None)`` used to surface
        the vectorization stage (the "sent for vectorization: N phrases"
        status) so the queued scoring job reports what the embedding service
        is doing.

    Raises
    ------
    EmbeddingUnavailable
        Propagated from ``fetch_vectors`` when the cache-miss batch cannot be
        vectorized.
    """
    unique = list(dict.fromkeys(texts))
    if not unique:
        return {}
    resolved = get_cached_vectors(conn, unique)
    missing = [text for text in unique if text not in resolved]
    if missing:
        if progress is not None:
            progress(
                message=(
                    f"Отправлено на векторизацию: {len(missing)} фраз "
                    f"(кэш {len(resolved)}/{len(unique)})"
                )
            )
        fetched = dict(zip(missing, fetch_vectors(base_url, missing, timeout=timeout)))
        store_vectors(conn, fetched)
        resolved.update(fetched)
    elif progress is not None:
        progress(message=f"Векторы из кэша: {len(resolved)}/{len(unique)}")
    return resolved


def _find_model_status(obj) -> str | None:
    """Recursively find ``embedding_service.status`` in a health payload.

    The embedding service health response nests the model readiness under
    ``components.model.embedding_service.status``, but the transport wrapper
    around it varies, so the value is located by a tolerant recursive search
    rather than a fixed path.
    """
    if isinstance(obj, dict):
        embedding_service = obj.get("embedding_service")
        if isinstance(embedding_service, dict) and "status" in embedding_service:
            status = embedding_service.get("status")
            if isinstance(status, str):
                return status
        for value in obj.values():
            found = _find_model_status(value)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_model_status(value)
            if found is not None:
                return found
    return None


async def _health_async(base_url: str, timeout: float):
    client = _client_from_url(base_url, timeout=timeout)
    try:
        return await client.health()
    finally:
        with contextlib.suppress(Exception):
            await client.close()


def embedding_health(base_url: str | None, timeout: float = 30.0) -> dict:
    """Return detailed embedding readiness, separating transport from model.

    Returns ``{"state", "transport_available", "model_ready", "model_status"}``
    where ``state`` is one of "unconfigured", "ready", "not_ready", or
    "unreachable"; ``transport_available`` is True when the health endpoint
    answered; ``model_ready`` is True only when the model reports
    ``status == "ready"``; and ``model_status`` is the raw model status string
    (or None).

    Queries the embedding service ``health`` command and inspects the model
    status, so a service that is transport-reachable but whose model is
    ``not_initialized`` is reported as ``not_ready`` rather than available.
    This distinction is what the info/health surfaces expose and what the
    semantic scoring preflight uses to fail fast instead of blocking on an
    uninitialized model.
    """
    if not base_url:
        return {
            "state": READINESS_UNCONFIGURED,
            "transport_available": False,
            "model_ready": False,
            "model_status": None,
        }
    try:
        health = _run_async_blocking(
            _health_async(base_url, timeout), timeout=timeout + 1.0
        )
    except (
        asyncio.TimeoutError,
        EmbedClientError,
        EmbedError,
        TimeoutError,
        OSError,
        RuntimeError,
    ):
        return {
            "state": READINESS_UNREACHABLE,
            "transport_available": False,
            "model_ready": False,
            "model_status": None,
        }
    status = _find_model_status(health)
    ready = status == "ready"
    return {
        "state": READINESS_READY if ready else READINESS_NOT_READY,
        "transport_available": True,
        "model_ready": ready,
        "model_status": status,
    }


def embedding_readiness(base_url: str | None, timeout: float = 30.0) -> str:
    """Return just the coarse embedding readiness state.

    Thin wrapper over :func:`embedding_health` returning its ``state``:
    one of "unconfigured", "ready", "not_ready", or "unreachable".
    """
    return embedding_health(base_url, timeout)["state"]
