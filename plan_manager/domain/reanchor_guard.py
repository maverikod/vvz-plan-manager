"""Reanchor target guard: refuses moving a runtime record's primary anchor onto a frozen-truth target (C-012)."""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.runtime_validation import FrozenTruthMutationError

def guard_reanchor_target_not_frozen(
    conn: psycopg.Connection,
    anchor_type: str,
    plan_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID | None,
) -> None:
    """Refuse a re-anchor move whose candidate new target is a frozen plan or a frozen step.

    Only the anchor_type/source_type values "plan" and "step" are backed by
    frozen-truth tables (plan, step); every other value (project, file,
    revision, execution_attempt, review_result, bug, bug_fix, todo, none,
    command, runtime_service, unidentified) is not a frozen-truth table and
    is not checked by this guard.

    Parameters:
        conn: psycopg.Connection
            Open connection used to read the candidate target's status.
        anchor_type: str
            The candidate new anchor type or bug source type being moved to.
        plan_uuid: uuid.UUID | None
            The candidate plan UUID; read when anchor_type == "plan".
        step_uuid: uuid.UUID | None
            The candidate step UUID; read when anchor_type == "step".

    Raises:
        FrozenTruthMutationError: When anchor_type == "plan" and the plan
            row's status column equals "frozen", or when anchor_type ==
            "step" and the step row's status column equals "frozen". Does
            not raise when no row is found for the candidate identifier (a
            separate existence check is the caller's responsibility).
    """
    if anchor_type == "plan":
        row = conn.execute(
            "SELECT status FROM plan WHERE uuid = %s", (plan_uuid,)
        ).fetchone()
        if row is not None and row[0] == "frozen":
            raise FrozenTruthMutationError(
                f"cannot re-anchor onto frozen plan {plan_uuid}"
            )
    elif anchor_type == "step":
        row = conn.execute(
            "SELECT status FROM step WHERE uuid = %s", (step_uuid,)
        ).fetchone()
        if row is not None and row[0] == "frozen":
            raise FrozenTruthMutationError(
                f"cannot re-anchor onto frozen step {step_uuid}"
            )
