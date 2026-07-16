"""Tests for step_delete's recursive extension (C-008 RecursiveSubtreeDelete, G-004).

Unit-style tests using the established monkeypatch _fake_db / fake-conn pattern
(no real database), matching tests/test_plan_unfreeze.py and
tests/test_step_transition_fast_fail.py.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from plan_manager.cascade.record import CascadeError, CascadeRecord
from plan_manager.cascade import write as write_mod
from plan_manager.commands import step_delete_command
from plan_manager.commands.step_delete_command import StepDeleteCommand
from plan_manager.domain import step_ops
from plan_manager.domain.plan import Plan
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000dd")

GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000101")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000102")
ATOMIC_UUID = uuid.UUID("00000000-0000-0000-0000-000000000103")


@contextmanager
def _fake_db():
    yield object()


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID, name="throwaway", status="draft", context_budget=4000,
        head_revision_uuid=HEAD_REV, project_ids=[], primary_project_id=None,
    )


def _step(step_uuid: uuid.UUID, level: int, step_id: str, parent, status: str = "draft") -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=step_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _tree(gs_status: str = "draft", ts_status: str = "draft", atomic_status: str = "draft") -> dict:
    gs = _step(GS_UUID, 3, "G-001", None, gs_status)
    ts = _step(TS_UUID, 4, "T-001", gs.uuid, ts_status)
    atomic = _step(ATOMIC_UUID, 5, "A-001", ts.uuid, atomic_status)
    return {s.uuid: s for s in (gs, ts, atomic)}


def _cascade_record(status: str = "open") -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(), plan_uuid=PLAN_UUID, name="cascade/x",
        base_revision_uuid=HEAD_REV, status=status, created_at=datetime.now(timezone.utc),
    )


def _raise_gone(conn, step_uuid) -> Step:
    raise ValueError("gone")


# --------------------------------------------------------------------- dry run preview


def test_recursive_dry_run_previews_entire_doomed_subtree(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", recursive=True, dry_run=True)
    )
    payload = result.to_dict()
    assert payload["success"] is True
    data = payload["data"]
    assert data["dry_run"] is True
    assert data["recursive"] is True
    assert data["would_delete"] == ["G-001", "G-001/T-001", "G-001/T-001/A-001"]


def test_non_recursive_dry_run_would_delete_is_target_path_only(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", dry_run=True)
    )
    payload = result.to_dict()
    data = payload["data"]
    assert data["recursive"] is False
    assert data["would_delete"] == "G-001"


# --------------------------------------------------------------------- refuse-when-children preserved


def test_non_recursive_real_run_refuses_when_children_present(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", dry_run=False)
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "INVALID_TRANSITION"


# --------------------------------------------------------------------- real recursive run: atomicity + tombstones


def test_recursive_real_run_deletes_whole_subtree_in_one_revision(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_delete_command, "check_admission", lambda conn, plan_uuid, kind, step_uuid, cid: None,
    )

    gs, ts, atomic = nodes[GS_UUID], nodes[TS_UUID], nodes[ATOMIC_UUID]

    def _fake_delete_subtree(conn, step_uuid):
        assert step_uuid == gs.uuid
        return [atomic, ts, gs]

    monkeypatch.setattr(step_delete_command, "delete_subtree", _fake_delete_subtree)

    captured: dict = {}

    def _fake_record_revision(conn, plan_uuid, author, message, changes, parent, ref_name):
        captured["changes"] = changes
        captured["ref_name"] = ref_name
        return uuid.uuid4()

    monkeypatch.setattr(step_delete_command, "record_revision", _fake_record_revision)
    monkeypatch.setattr(step_delete_command, "get_step", _raise_gone)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", dry_run=False, recursive=True)
    )
    payload = result.to_dict()
    assert payload["success"] is True
    data = payload["data"]
    assert data["recursive"] is True
    assert data["deleted_step_id"] == "G-001"
    assert data["deleted_step_ids"] == ["A-001", "T-001", "G-001"]

    # single revision: one record_revision call carrying every tombstone.
    assert captured["ref_name"] is None
    assert len(captured["changes"]) == 3
    deleted_uuids = {node_uuid for node_uuid, _snapshot in captured["changes"]}
    assert deleted_uuids == {gs.uuid, ts.uuid, atomic.uuid}
    for _node_uuid, snapshot in captured["changes"]:
        assert snapshot["deleted"] is True


def test_recursive_real_run_admitted_under_cascade_writes_one_revision(monkeypatch) -> None:
    nodes = _tree()
    cascade = _cascade_record()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_delete_command, "check_admission",
        lambda conn, plan_uuid, kind, step_uuid, cid: cascade,
    )

    gs, ts, atomic = nodes[GS_UUID], nodes[TS_UUID], nodes[ATOMIC_UUID]
    monkeypatch.setattr(step_delete_command, "delete_subtree", lambda conn, step_uuid: [atomic, ts, gs])

    captured: dict = {}

    def _fake_cascade_write_many(conn, plan_uuid, rec, node_changes, status_updates, author, message):
        captured["node_changes"] = node_changes
        captured["cascade_name"] = rec.name
        captured["status_updates"] = status_updates
        return uuid.uuid4()

    monkeypatch.setattr(step_delete_command, "cascade_write_many", _fake_cascade_write_many)
    monkeypatch.setattr(step_delete_command, "get_step", _raise_gone)

    result = asyncio.run(
        StepDeleteCommand().execute(
            plan="p", step_id="G-001", dry_run=False, recursive=True,
            cascade_uuid=str(cascade.uuid),
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert captured["cascade_name"] == cascade.name
    assert captured["status_updates"] == []
    assert len(captured["node_changes"]) == 3
    for _node_uuid, snapshot in captured["node_changes"]:
        assert snapshot["deleted"] is True


# --------------------------------------------------------------------- admission-regime conformance


def test_recursive_bypasses_refusal_but_frozen_target_needs_cascade(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    def _raise_cascade_error(conn, plan_uuid, kind, step_uuid, cascade_uuid):
        raise CascadeError("step is not directly mutable")

    monkeypatch.setattr(step_delete_command, "check_admission", _raise_cascade_error)
    monkeypatch.setattr(step_delete_command, "frozen_at_or_below", lambda nodes, step_uuid: True)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", dry_run=False, recursive=True)
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "FROZEN_ARTIFACT"


def test_recursive_bypasses_refusal_but_open_cascade_elsewhere_needs_cascade_uuid(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    def _raise_cascade_error(conn, plan_uuid, kind, step_uuid, cascade_uuid):
        raise CascadeError("plan has an open cascade; direct mutation rejected")

    monkeypatch.setattr(step_delete_command, "check_admission", _raise_cascade_error)
    monkeypatch.setattr(step_delete_command, "frozen_at_or_below", lambda nodes, step_uuid: False)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="G-001", dry_run=False, recursive=True)
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"


def test_recursive_real_run_cascade_conflict_when_cascade_uuid_wrong(monkeypatch) -> None:
    nodes = _tree()
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)

    def _raise_cascade_error(conn, plan_uuid, kind, step_uuid, cascade_uuid):
        raise CascadeError("cascade id does not match the open cascade")

    monkeypatch.setattr(step_delete_command, "check_admission", _raise_cascade_error)

    result = asyncio.run(
        StepDeleteCommand().execute(
            plan="p", step_id="G-001", dry_run=False, recursive=True,
            cascade_uuid=str(uuid.uuid4()),
        )
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"


# --------------------------------------------------------------------- domain: delete_subtree ordering


class _Rows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_delete_subtree_deletes_leaves_before_ancestors(monkeypatch) -> None:
    nodes = _tree()
    gs, ts, atomic = nodes[GS_UUID], nodes[TS_UUID], nodes[ATOMIC_UUID]

    children_of = {
        gs.uuid: [ts.uuid],
        ts.uuid: [atomic.uuid],
        atomic.uuid: [],
    }

    class _FakeConn:
        def execute(self_inner, sql, params=()):
            assert sql == "SELECT uuid FROM step WHERE parent_step_uuid = ANY(%s)"
            frontier = params[0]
            rows = [(child,) for parent in frontier for child in children_of.get(parent, [])]
            return _Rows(rows)

    monkeypatch.setattr(step_ops, "get_step", lambda conn, step_uuid: nodes[step_uuid])
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(step_ops, "delete_step", lambda conn, step_uuid: calls.append(step_uuid))

    deleted = step_ops.delete_subtree(_FakeConn(), gs.uuid)

    assert calls == [atomic.uuid, ts.uuid, gs.uuid]
    assert [s.uuid for s in deleted] == [atomic.uuid, ts.uuid, gs.uuid]


# --------------------------------------------------------------------- cascade.write.cascade_write_many


def test_cascade_write_many_records_all_node_changes_plus_status_updates(monkeypatch) -> None:
    cascade = _cascade_record()
    calls: dict = {}

    monkeypatch.setattr(write_mod, "get_ref", lambda conn, plan_uuid, name: HEAD_REV)
    monkeypatch.setattr(write_mod, "apply_status_updates", lambda conn, updates: [])

    def _fake_record_revision(conn, plan_uuid, author, message, changes, parent, ref_name):
        calls["changes"] = changes
        calls["parent"] = parent
        calls["ref_name"] = ref_name
        return uuid.uuid4()

    monkeypatch.setattr(write_mod, "record_revision", _fake_record_revision)

    node_changes = [(uuid.uuid4(), {"kind": "step", "deleted": True}) for _ in range(3)]
    revision = write_mod.cascade_write_many(
        object(), PLAN_UUID, cascade, node_changes, [], "api", "step_delete(recursive): G-001",
    )

    assert isinstance(revision, uuid.UUID)
    assert calls["changes"] == node_changes
    assert calls["parent"] == HEAD_REV
    assert calls["ref_name"] == cascade.name


def test_cascade_write_many_refuses_when_cascade_not_open() -> None:
    closed = _cascade_record(status="committed")
    with pytest.raises(CascadeError):
        write_mod.cascade_write_many(object(), PLAN_UUID, closed, [], [], "api", "msg")
