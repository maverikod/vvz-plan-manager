"""Aggregate plan.status sync (bug 845b43a8).

plan.status is a derived summary of the step lifecycle tree, not an
independently authored field: it is 'frozen' iff the plan owns at least one
step and every step's status is 'frozen'; it is 'draft' otherwise (including
an empty step set, which is authoring-stage). Before this module existed,
plan.status was written once at create_plan() time and never touched again
(see the historical comment removed from cascade.begin._all_steps_frozen),
so a fully frozen plan still reported 'draft' forever in plan_status and
plan_list. This module is now the only place plan.status is written outside
create_plan, and it is called from two sites:

  * step_transition (any scope, including whole_plan): after applying the
    per-step UPDATEs, the caller recomputes the aggregate from the in-memory
    step tree it already loaded for the transition and stores it. This
    covers a straight whole_plan freeze AND the case where freezing or
    unfreezing a partial scope happens to complete or break a full freeze of
    the whole tree -- the aggregate is always derived from the WHOLE tree,
    never just the transitioned scope.
  * plan_unfreeze: opening an audited cascade on a fully frozen plan makes
    the plan editable again immediately, before any step has actually moved
    -- the aggregate is force-reset to 'draft' here rather than derived,
    because the tree itself is still all-frozen at that instant and deriving
    it would (wrongly) keep reporting 'frozen' while the plan is open for
    editing.

set_plan_status uses a plain conn.execute UPDATE, matching the existing
raw-SQL setters in plan_manager.domain.plan (set_plan_completed,
set_plan_comment, set_head_revision). The CR-7 G-004
cr7-no-out-of-mechanism-write scan (plan_manager/pipeline_checks/registry.py)
flags only INSERT INTO / DELETE FROM on registered tables, so this plain
UPDATE needs no compatibility marker.

Never touches plan.completed (bug c3950b83): that lock is independent of the
draft/frozen aggregate this module owns.
"""

from __future__ import annotations

import uuid
from typing import Iterable

import psycopg


PLAN_STATUS_DRAFT = "draft"
PLAN_STATUS_FROZEN = "frozen"


def derive_plan_status(step_statuses: Iterable[str]) -> str:
    """Return the aggregate plan status for one plan's full set of step statuses.

    Args:
        step_statuses: The current status of every step belonging to one
            plan -- the WHOLE tree, never just a scope -- post-transition.

    Returns:
        PLAN_STATUS_FROZEN when the iterable is non-empty and every status
        equals 'frozen'; PLAN_STATUS_DRAFT otherwise (an empty tree is
        authoring-stage, not frozen).
    """
    statuses = list(step_statuses)
    if not statuses:
        return PLAN_STATUS_DRAFT
    if all(status == PLAN_STATUS_FROZEN for status in statuses):
        return PLAN_STATUS_FROZEN
    return PLAN_STATUS_DRAFT


def set_plan_status(conn: psycopg.Connection, plan_uuid: uuid.UUID, status: str) -> None:
    """Persist the plan's aggregate status column directly.

    Args:
        conn: Open psycopg 3 connection, part of the caller's open
            transaction -- the write is only atomic with a sibling step
            mutation because both share this same connection/transaction.
        plan_uuid: Primary identity of the plan to update.
        status: The new aggregate status. Callers only ever pass
            PLAN_STATUS_DRAFT or PLAN_STATUS_FROZEN; not validated here.

    Returns:
        None.
    """
    conn.execute("UPDATE plan SET status = %s WHERE uuid = %s", (status, plan_uuid))
