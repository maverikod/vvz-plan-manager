"""Verdict binding for gate and scoring results (C-020 Verdict).

A Verdict binds a gate or score result to the exact revision and scope it
was computed for. Verdicts are returned to the caller and never persisted:
no timestamp field exists anywhere in this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg


class VerdictError(ValueError):
    """Raised when a Verdict is constructed with an invalid kind, or when
    current_head_revision is asked about a plan_uuid that has no row."""


@dataclass(frozen=True)
class Verdict:
    """A gate or score result bound to the exact revision and scope it was
    computed for.

    Attributes:
        kind: Either "gate" or "score".
        scope: "plan" or a branch artifact path such as "G-001/T-002/A-003".
        revision_uuid: The plan revision identifier the result was computed
            on, or None.
        green: True iff the result is green (no findings / passes threshold).
        payload: The run's result data.

    Raises:
        VerdictError: If kind is not one of "gate" or "score".
    """

    kind: str
    scope: str
    revision_uuid: uuid.UUID | None
    green: bool
    payload: dict

    def __post_init__(self) -> None:
        if self.kind not in ("gate", "score"):
            raise VerdictError(f"invalid Verdict kind: {self.kind}")


def current_head_revision(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> uuid.UUID | None:
    """Look up the current head revision of a plan."""
    with conn.cursor() as cur:
        cur.execute("SELECT head_revision_uuid FROM plan WHERE uuid = %s", (plan_uuid,))
        row = cur.fetchone()
    if row is None:
        raise VerdictError(f"no plan with uuid: {plan_uuid}")
    return row[0]


def is_fresh(verdict: Verdict, current_revision_uuid: uuid.UUID | None) -> bool:
    """Decide whether a Verdict is fresh against a current revision."""
    return verdict.revision_uuid == current_revision_uuid

