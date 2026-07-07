"""Shared service-reachability probes for the info and health commands.

Both the ``info`` self-description (C-025) and the platform ``health``
override report the availability of the services plan_manager depends on:
the in-container PostgreSQL database (required) and the optional embedding
service. Centralizing the probes here keeps the two commands' verdicts
identical for one runtime state and ensures both honor the operator's
configured embedding timeout rather than an ad-hoc constant.
"""

from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.embedding import EmbeddingUnavailable, fetch_vector

EMBEDDING_UNCONFIGURED = "unconfigured"
EMBEDDING_REACHABLE = "reachable"
EMBEDDING_UNREACHABLE = "unreachable"

_PROBE_TEXT = "probe"


def probe_database() -> bool:
    """Return True when a trivial query succeeds on a fresh connection."""
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


def probe_embedding() -> str:
    """Return the embedding service reachability state.

    Returns ``"unconfigured"`` when no embedding URL is set, ``"reachable"``
    when a probe embedding is returned within the configured timeout, and
    ``"unreachable"`` when the service cannot be reached in time or returns
    a malformed response. The probe uses the operator-configured
    ``embedding.timeout`` so a healthy-but-not-instant service (a cold model
    load or a multi-second async job) is not misreported as unreachable.
    """
    cfg = app_config()
    if cfg.embedding_url is None:
        return EMBEDDING_UNCONFIGURED
    try:
        fetch_vector(cfg.embedding_url, _PROBE_TEXT, timeout=cfg.embedding_timeout)
        return EMBEDDING_REACHABLE
    except EmbeddingUnavailable:
        return EMBEDDING_UNREACHABLE
