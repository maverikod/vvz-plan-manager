"""Embedding client and cache for EmbeddingService (C-022) integration.

Provides text embedding retrieval with a database-backed cache keyed by
content hash, and an explicit typed unavailability condition instead of
raising on service failure.
"""

import json
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

import psycopg

from plan_manager.storage.canonical import content_hash


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


def fetch_vector(base_url: str, text: str) -> list[float]:
    """Request the embedding vector for ``text`` from the external embedding service.

    Parameters
    ----------
    base_url:
        The configured URL of the embedding service endpoint.
    text:
        The text to embed.

    Returns
    -------
    list[float]
        The embedding vector returned by the service.

    Raises
    ------
    EmbeddingUnavailable
        Raised, carrying the reason as its argument, for every deviation
        from the normative protocol: a connection error, a timeout, a
        non-200 HTTP status, a malformed (non-JSON) response body, or a
        response body whose JSON has no "embedding" key or whose
        "embedding" value is not a list.

    Behavior
    --------
    Sends an HTTP POST request to ``base_url`` with body
    ``json.dumps({"input": text}).encode("utf-8")``, header
    ``Content-Type: application/json``, and a timeout of 10.0 seconds,
    using ``urllib.request`` only. On HTTP 200, parses the response body
    as JSON and returns the value of its "embedding" key as a list of
    floats.
    """
    payload = json.dumps({"input": text}).encode("utf-8")
    request = urllib.request.Request(
        base_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10.0) as response:
            status = response.status
            body = response.read()
    except urllib.error.URLError as exc:
        raise EmbeddingUnavailable(str(exc)) from exc
    except OSError as exc:
        raise EmbeddingUnavailable(str(exc)) from exc

    if status != 200:
        raise EmbeddingUnavailable(f"unexpected HTTP status {status}")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise EmbeddingUnavailable(f"malformed JSON response: {exc}") from exc

    if not isinstance(parsed, dict) or "embedding" not in parsed:
        raise EmbeddingUnavailable("response JSON missing 'embedding' key")

    embedding = parsed["embedding"]
    if not isinstance(embedding, list):
        raise EmbeddingUnavailable("'embedding' value is not a list")

    return embedding


def embed_text(conn: psycopg.Connection, base_url: str, text: str) -> list[float]:
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
    stores the result via ``store_vector(conn, text, vector)``, and
    returns the vector.
    """
    cached = get_cached_vector(conn, text)
    if cached is not None:
        return cached
    vector = fetch_vector(base_url, text)
    store_vector(conn, text, vector)
    return vector
