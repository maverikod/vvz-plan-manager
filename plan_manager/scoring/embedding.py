"""Embedding client and cache for EmbeddingService (C-022) integration.

Provides text embedding retrieval with a database-backed cache keyed by
content hash, and an explicit typed unavailability condition instead of
raising on service failure.

The batch layer (cache-first array vectorization through one queued embedding
job) and the model-readiness probe live in
:mod:`plan_manager.scoring.embedding_batch`, which builds on the primitives
here; they are split out to keep this module within the file-size limit.
"""

import json
import asyncio
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from embed_client import EmbeddingClient
from embed_client.exceptions import EmbedClientError, EmbedError
import psycopg

from plan_manager.storage.canonical import content_hash


# Embedding model readiness states (see embedding_batch.embedding_readiness).
READINESS_UNCONFIGURED = "unconfigured"
READINESS_READY = "ready"
READINESS_NOT_READY = "not_ready"
READINESS_UNREACHABLE = "unreachable"


class EmbeddingUnavailable(Exception):
    """Raised when the embedding service cannot be reached or returns a
    malformed response.

    Carries the reason as its single string argument. Callers catch this
    exception to degrade semantic scoring only; every other function keeps
    working when the embedding service is unavailable.
    """


def text_content_hash(text: str) -> str:
    """Return the canonical content hash of ``text``.

    Parameters
    ----------
    text:
        The text whose content hash is computed.

    Returns
    -------
    str
        The SHA-256 hex digest of the canonical JSON of ``text``, as
        produced by ``plan_manager.storage.canonical.content_hash``.
    """
    return content_hash(text)


def get_cached_vector(conn: psycopg.Connection, text: str) -> list[float] | None:
    """Look up a cached embedding vector by the content hash of ``text``.

    Parameters
    ----------
    conn:
        An open psycopg 3 database connection.
    text:
        The text whose cached vector is looked up; the lookup key is its
        content hash via ``text_content_hash``.

    Returns
    -------
    list[float] | None
        The cached vector as a list of floats if a row exists for the
        content hash, or ``None`` if there is no cached vector.
    """
    key = text_content_hash(text)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vector::text FROM embedding_cache WHERE content_hash = %s",
            (key,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def store_vector(conn: psycopg.Connection, text: str, vector: list[float]) -> None:
    """Store an embedding vector in the cache keyed by the content hash of ``text``.

    Parameters
    ----------
    conn:
        An open psycopg 3 database connection.
    text:
        The text whose vector is being cached; the cache key is its content
        hash via ``text_content_hash``.
    vector:
        The embedding vector to store, as a list of floats.

    Returns
    -------
    None

    Behavior
    --------
    Inserts one row into ``embedding_cache`` with a freshly generated
    ``uuid.uuid4()`` as ``uuid``, the content hash of ``text`` as
    ``content_hash``, ``vector`` (JSON-encoded via ``json.dumps`` and cast
    to ``::vector``) as ``vector``, and ``datetime.now(timezone.utc)`` as
    ``created_at``. On a content-hash conflict the insert is a no-op
    (``ON CONFLICT (content_hash) DO NOTHING``).
    """
    key = text_content_hash(text)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO embedding_cache (uuid, content_hash, vector, created_at) "
            "VALUES (%s, %s, %s::vector, %s) "
            "ON CONFLICT (content_hash) DO NOTHING",
            (uuid.uuid4(), key, json.dumps(vector), datetime.now(timezone.utc)),
        )


def _run_async_blocking(coro, timeout: float | None = None):
    """Run *coro* from synchronous scoring code, even inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if timeout is None:
            return asyncio.run(coro)
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))

    result: list[object] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError(f"embedding request timed out after {timeout} seconds")
    if error:
        raise error[0]
    return result[0]


def _client_from_url(base_url: str, timeout: float = 60.0) -> EmbeddingClient:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise EmbeddingUnavailable(f"unsupported embedding URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise EmbeddingUnavailable("embedding URL must include a host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return EmbeddingClient(
        protocol=parsed.scheme,
        host=parsed.hostname,
        port=port,
        check_hostname=False,
        timeout=timeout,
    )


async def _fetch_vector_async(base_url: str, text: str, timeout: float) -> list[float]:
    client = _client_from_url(base_url, timeout=timeout)
    result = await client.embed([text], wait=True, wait_timeout=timeout)
    results = result.get("results")
    if not isinstance(results, list) or not results:
        raise EmbeddingUnavailable("embed-client response missing results")
    first = results[0]
    if not isinstance(first, dict):
        raise EmbeddingUnavailable("embed-client result item is not an object")
    embedding = first.get("embedding")
    if not isinstance(embedding, list):
        raise EmbeddingUnavailable("embed-client result missing embedding list")
    return embedding


def fetch_vector(base_url: str, text: str, timeout: float = 60.0) -> list[float]:
    """Request the embedding vector for ``text`` through embed-client.

    Parameters
    ----------
    base_url:
        The configured base URL of the embedding service, for example
        ``https://192.168.254.26:8001``.
    text:
        The text to embed.

    Returns
    -------
    list[float]
        The embedding vector returned by the service.

    Raises
    ------
    EmbeddingUnavailable
        Raised, carrying the reason as its argument, when embed-client
        cannot reach the service, the job fails or times out, or the
        completed response does not contain a vector.

    Behavior
    --------
    Uses :class:`embed_client.EmbeddingClient`, which talks to the
    embedding service through the mcp-proxy-adapter JSON-RPC command
    surface and waits for completion through the client-supported
    async path. The rest of plan_manager's scoring code is synchronous,
    so this function bridges the async client in a blocking wrapper.
    """
    try:
        return _run_async_blocking(
            _fetch_vector_async(base_url, text, timeout),
            timeout=timeout + 1.0,
        )
    except (asyncio.TimeoutError, EmbedClientError, EmbedError, TimeoutError, OSError, RuntimeError) as exc:
        raise EmbeddingUnavailable(str(exc)) from exc


def embed_text(
    conn: psycopg.Connection,
    base_url: str,
    text: str,
    timeout: float = 60.0,
) -> list[float]:
    """Return the embedding vector for ``text``, using the cache first.

    Parameters
    ----------
    conn:
        An open psycopg 3 database connection.
    base_url:
        The configured URL of the embedding service endpoint, passed to
        ``fetch_vector`` on a cache miss.
    text:
        The text whose embedding vector is requested.
    timeout:
        Per-request timeout in seconds passed to ``fetch_vector`` on a
        cache miss; the operator-configured embedding timeout.

    Returns
    -------
    list[float]
        The embedding vector for ``text``.

    Raises
    ------
    EmbeddingUnavailable
        Propagated from ``fetch_vector`` when the embedding service cannot
        be reached or returns a malformed response.

    Behavior
    --------
    Looks up ``text`` in the cache via ``get_cached_vector``. On a cache
    hit, returns the cached vector without contacting the embedding
    service. On a cache miss, calls ``fetch_vector(base_url, text)``,
    stores the result via ``store_vector(conn, text, vector)``, then
    re-reads the stored vector via ``get_cached_vector`` and returns that
    read-back value (falling back to the freshly fetched vector only if the
    re-read unexpectedly returns None).

    The write-then-read-back is what makes ``embed_text`` deterministic
    across runs: the embedding service returns float64 vectors, while the
    pgvector cache stores and returns float4, so a first run that returned
    the service-fresh vector and a later run that returned the cache-read
    vector produced values that differed at ~1e-9 — enough to change a
    tree hash and defeat snapshot deduplication. Returning the
    cache-representation vector on every path removes that divergence.
    """
    cached = get_cached_vector(conn, text)
    if cached is not None:
        return cached
    vector = fetch_vector(base_url, text, timeout=timeout)
    store_vector(conn, text, vector)
    reread = get_cached_vector(conn, text)
    return reread if reread is not None else vector
