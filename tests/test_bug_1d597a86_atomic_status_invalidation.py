"""Regression matrix for bug 1d597a86.

Cascade invalidation below a changed GS/TS must not erase atomic execution
progress, while still invalidating non-atomic descendants and atomic authoring
statuses that are not execution terminal/in-flight states.
"""

from __future__ import annotations

import uuid

from plan_manager.cascade.propagation import step_invalidation
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000011")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000012")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000013")


def _step(
    step_uuid: uuid.UUID,
    level: int,
    step_id: str,
    parent: uuid.UUID | None,
    status: str,
) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=step_uuid,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status=status,
    )


def _tree(*, ts_status: str = "needs_review", atomic_status: str) -> dict[uuid.UUID, Step]:
    gs = _step(GS_UUID, 3, "G-001", None, "draft")
    ts = _step(TS_UUID, 4, "T-001", gs.uuid, ts_status)
    atomic = _step(AS_UUID, 5, "A-001", ts.uuid, atomic_status)
    return {step.uuid: step for step in (gs, ts, atomic)}


def test_bug_1d597a86_atomic_execution_status_survives_invalidation_done() -> None:
    assert step_invalidation(_tree(atomic_status="done"), GS_UUID) == []


def test_bug_1d597a86_atomic_execution_status_survives_invalidation_in_progress() -> None:
    assert step_invalidation(_tree(atomic_status="in_progress"), GS_UUID) == []


def test_bug_1d597a86_atomic_other_statuses_invalidate_to_needs_review() -> None:
    updates = step_invalidation(_tree(atomic_status="frozen"), GS_UUID)

    assert updates == [(AS_UUID, "needs_review")]


def test_bug_1d597a86_atomic_needs_review_is_skipped() -> None:
    assert step_invalidation(_tree(atomic_status="needs_review"), GS_UUID) == []


def test_bug_1d597a86_non_atomic_descendants_remain_invalidatable() -> None:
    updates = step_invalidation(_tree(ts_status="frozen", atomic_status="needs_review"), GS_UUID)

    assert updates == [(TS_UUID, "needs_review")]
