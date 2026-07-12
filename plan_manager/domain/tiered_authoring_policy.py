"""Tiered authoring policy: seed/example configuration mapping runtime roles to model tiers,
expressed as model-binding create-specs — DATA, never hard-coded domain logic (C-013)."""

from __future__ import annotations
from typing import Any

TIERED_AUTHORING_POLICY: tuple[dict[str, str], ...] = (
    {"role": "hrs_author", "provider": "anthropic", "model": "fable"},
    {"role": "mrs_author", "provider": "anthropic", "model": "fable"},
    {"role": "gs_author",  "provider": "anthropic", "model": "opus"},
    {"role": "ts_author",  "provider": "anthropic", "model": "sonnet"},
    {"role": "as_author",  "provider": "anthropic", "model": "haiku"},
    {"role": "code_executor", "provider": "vast_qwen", "model": "qwen"},
)

DEFAULT_MAX_RETRIES: int = 1
DEFAULT_TIMEOUT: int = 600


def build_policy_bindings(
    policy: tuple[dict[str, str], ...] = TIERED_AUTHORING_POLICY, *, created_by: str,
) -> list[dict[str, Any]]:
    """Transform a tiered authoring policy into model-binding create-specs."""
    return [
        {
            "scope": "role",
            "role": row["role"],
            "provider": row["provider"],
            "model": row["model"],
            "max_retries": DEFAULT_MAX_RETRIES,
            "timeout": DEFAULT_TIMEOUT,
            "active": True,
            "created_by": created_by,
        }
        for row in policy
    ]
