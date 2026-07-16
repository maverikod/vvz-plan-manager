"""Unit tests for the context-block currency helpers (C-003):
current_working_state and has_current_common_block, added to
plan_manager/views/context_blocks.py by CR-4 G-001/T-001.

All tests are unit-style with fake connection/plan objects and
monkeypatch.setattr on the context_blocks module's imported names,
matching the established pattern in tests/test_context_blocks.py and
tests/test_plan_unfreeze.py (no real database).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from plan_manager.cascade.record import CascadeRecord
from plan_manager.domain.plan import Plan
from plan_manager.views import context_blocks
from plan_manager.views.context_blocks import current_working_state, has_current_common_block


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-000000000002")
CASCADE_REF_REV = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="throwaway",
        status="draft",
        context_budget=4000,
        head_revision_uuid=HEAD_REV,
        project_ids=[],
        primary_project_id=None,
    )


def _cascade() -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        name="cascade/x",
        base_revision_uuid=HEAD_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


def test_current_working_state_uses_head_revision_when_no_open_cascade(monkeypatch) -> None:
    monkeypatch.setattr(context_blocks, "get_open_cascade", lambda conn, plan_uuid: None)

    revision, cascade_uuid = current_working_state(object(), _plan())

    assert revision == HEAD_REV
    assert cascade_uuid is None


def test_current_working_state_uses_cascade_ref_when_cascade_open(monkeypatch) -> None:
    cascade = _cascade()
    monkeypatch.setattr(context_blocks, "get_open_cascade", lambda conn, plan_uuid: cascade)

    def _fake_get_ref(conn, plan_uuid, name):
        assert plan_uuid == PLAN_UUID
        assert name == cascade.name
        return CASCADE_REF_REV

    monkeypatch.setattr(context_blocks, "get_ref", _fake_get_ref)

    revision, cascade_uuid = current_working_state(object(), _plan())

    assert revision == CASCADE_REF_REV
    assert cascade_uuid == cascade.uuid


class _One:
    def fetchone(self):
        return (1,)


class _Empty:
    def fetchone(self):
        return None


class _FakeConn:
    """Fake connection whose stored rows simulate IS NOT DISTINCT FROM matching."""

    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.last_params: tuple | None = None

    def execute(self, sql: str, params: tuple):
        self.last_params = params
        plan_uuid, node_path, child_level, revision_uuid, cascade_uuid = params
        for row in self._rows:
            if (
                row[0] == plan_uuid
                and row[1] == node_path
                and row[2] == child_level
                and row[3] == revision_uuid
                and row[4] == cascade_uuid
            ):
                return _One()
        return _Empty()


def test_has_current_common_block_true_when_matching_row_exists() -> None:
    conn = _FakeConn([(PLAN_UUID, "G-001", 4, HEAD_REV, None)])

    assert has_current_common_block(conn, PLAN_UUID, "G-001", 4, HEAD_REV, None) is True


def test_has_current_common_block_false_when_no_matching_row() -> None:
    conn = _FakeConn([])

    assert has_current_common_block(conn, PLAN_UUID, "G-001", 4, HEAD_REV, None) is False


def test_has_current_common_block_stale_revision_counts_as_absent() -> None:
    stale_rev = uuid.UUID("00000000-0000-0000-0000-0000000000ee")
    conn = _FakeConn([(PLAN_UUID, "G-001", 4, stale_rev, None)])

    assert has_current_common_block(conn, PLAN_UUID, "G-001", 4, HEAD_REV, None) is False


def test_has_current_common_block_null_safe_on_cascade_uuid() -> None:
    cascade_uuid = uuid.uuid4()
    conn = _FakeConn([(PLAN_UUID, "G-001/T-001", 5, CASCADE_REF_REV, cascade_uuid)])

    assert has_current_common_block(
        conn, PLAN_UUID, "G-001/T-001", 5, CASCADE_REF_REV, cascade_uuid
    ) is True
    assert has_current_common_block(
        conn, PLAN_UUID, "G-001/T-001", 5, CASCADE_REF_REV, None
    ) is False
