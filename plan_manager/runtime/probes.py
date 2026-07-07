"""Shared service-reachability probes for the info and health commands.

Both the ``info`` self-description (C-025) and the platform ``health``
override report the availability of the services plan_manager depends on:
the in-container PostgreSQL database (required) and the optional embedding
service. Centralizing the probes here keeps the two commands' verdicts
identical for one runtime state and ensures both honor the operator's
configured embedding timeout rather than an ad-hoc constant.

The embedding probe distinguishes a transport-reachable service from an
initialized model: it queries the embedding service health and inspects the
model status, so a service that answers but whose model is ``not_initialized``
is reported as ``not_ready`` rather than available. This is the same signal
semantic scoring uses to fail fast instead of blocking on an uninitialized
model.
"""

from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.embedding import (
    READINESS_NOT_READY,
    READINESS_READY,
    READINESS_UNCONFIGURED,
    READINESS_UNREACHABLE,
)
from plan_manager.scoring.embedding_batch import embedding_health, embedding_readiness

# Backward-compatible aliases (info/health import these names).
EMBEDDING_UNCONFIGURED = READINESS_UNCONFIGURED
EMBEDDING_READY = READINESS_READY
EMBEDDING_NOT_READY = READINESS_NOT_READY
EMBEDDING_UNREACHABLE = READINESS_UNREACHABLE


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
    """Return the coarse embedding readiness state.

    One of ``"unconfigured"``, ``"ready"``, ``"not_ready"``, or
    ``"unreachable"``, using the operator-configured embedding timeout.
    """
    cfg = app_config()
    return embedding_readiness(cfg.embedding_url, cfg.embedding_timeout)


def probe_embedding_detail() -> dict:
    """Return detailed embedding readiness for the health surface.

    ``{"state", "transport_available", "model_ready", "model_status"}`` —
    separating whether the service answered (``transport_available``) from
    whether its model is initialized (``model_ready``).
    """
    cfg = app_config()
    return embedding_health(cfg.embedding_url, cfg.embedding_timeout)
