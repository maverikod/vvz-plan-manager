"""Cross-branch integration test for CR-4 (C-010): the REAL ancestor-frozen
detection added by the membership-invariant closure (cascade.regime
frozen_ancestor / check_admission) must drive the REAL recursive deletion
path of step_delete -- no mocking of check_admission or frozen_ancestor.

Closes the cross-cutting gap between the two sibling suites: the
recursive-delete suite exercises step_delete's response to a MOCKED
check_admission outcome, while the membership-invariant suite exercises the
REAL check_admission through step_move but never through step_delete. This
module wires the two real mechanisms together end to end.

Unit-style, no real database: monkeypatch module-level names on
step_delete_command and on cascade.regime (get_open_cascade / load_steps
only -- never check_admission or frozen_ancestor themselves), matching the
established pattern of tests/test_frozen_subtree_membership_invariant.py.
"""
from __future__ import annotations

import asyncio
import datetime
import uuid
from contextlib import contextmanager

from plan_manager.cascade import regime as regime_mod
from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import step_delete_command
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_delete_command import StepDeleteCommand
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")

GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000011")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000012")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000013")


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REV


@contextmanager
def _fake_db():
    yield object()


def _step(step_uuid: uuid.UUID, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=step_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _tree(gs_status: str) -> dict[uuid.UUID, Step]:
    """G-001 (gs_status) -> T-001 (draft) -> A-001 (draft).

    With gs_status='frozen', the delete target T-001 is itself draft and has
    only a draft descendant, so frozen_at_or_below(T-001) is False -- any
    refusal can come only from the ancestor walk inside the real
    check_admission."""
    gs = _step(GS_UUID, 3, "G-001", None, gs_status)
    ts = _step(TS_UUID, 4, "T-001", gs.uuid, "draft")
    atomic = _step(AS_UUID, 5, "A-001", ts.uuid, "draft")
    return {s.uuid: s for s in (gs, ts, atomic)}


def _patch_common(monkeypatch, nodes, open_cascade) -> dict:
    calls: dict = {}
    monkeypatch.setattr(step_delete_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_delete_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_delete_command, "load_steps", lambda conn, plan_uuid: nodes)
    # The REAL check_admission (imported by name into step_delete_command)
    # stays unpatched; only its own database seams on the regime module are
    # faked, exactly as tests/test_frozen_subtree_membership_invariant.py does.
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: open_cascade)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    def _delete_subtree(conn, target_uuid):
        calls["delete_subtree"] = target_uuid
        return [nodes[AS_UUID], nodes[TS_UUID]]

    monkeypatch.setattr(step_delete_command, "delete_subtree", _delete_subtree)

    def _cascade_write_many(conn, plan_uuid, rec, node_changes, status_updates, actor, message):
        calls["cascade_write_many"] = {
            "node_changes": node_changes, "status_updates": status_updates, "message": message,
        }
        return uuid.uuid4()

    monkeypatch.setattr(step_delete_command, "cascade_write_many", _cascade_write_many)

    def _record_revision(conn, plan_uuid, actor, message, changes, parent, ref_name=None):
        calls["record_revision"] = {"changes": changes, "message": message}
        return uuid.uuid4()

    monkeypatch.setattr(step_delete_command, "record_revision", _record_revision)

    def _get_step_raises(conn, target_uuid):
        raise DomainCommandError("STEP_NOT_FOUND", "deleted")

    monkeypatch.setattr(step_delete_command, "get_step", _get_step_raises)
    return calls


def _open_cascade_record(cascade_uuid: uuid.UUID) -> CascadeRecord:
    return CascadeRecord(
        uuid=cascade_uuid, plan_uuid=PLAN_UUID, name="cascade/x",
        base_revision_uuid=uuid.uuid4(), status="open",
        created_at=datetime.datetime.now(datetime.timezone.utc),
    )


# ------------------------------------------------- frozen ancestor refuses the real recursive delete


def test_recursive_delete_under_frozen_ancestor_is_refused_by_real_admission(monkeypatch) -> None:
    nodes = _tree(gs_status="frozen")
    calls = _patch_common(monkeypatch, nodes, open_cascade=None)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="T-001", dry_run=False, recursive=True)
    )

    payload = result.to_dict()
    assert payload["success"] is False
    # T-001 itself and its only descendant are draft, so frozen_at_or_below
    # is False and the refusal classifies as CASCADE_REQUIRED -- proving the
    # CascadeError originated in the REAL check_admission's ancestor walk.
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"
    assert "delete_subtree" not in calls
    assert "cascade_write_many" not in calls
    assert "record_revision" not in calls


def test_recursive_delete_under_frozen_ancestor_is_admitted_by_matching_cascade(monkeypatch) -> None:
    nodes = _tree(gs_status="frozen")
    cascade_uuid = uuid.uuid4()
    rec = _open_cascade_record(cascade_uuid)
    calls = _patch_common(monkeypatch, nodes, open_cascade=rec)

    result = asyncio.run(
        StepDeleteCommand().execute(
            plan="p", step_id="T-001", cascade_uuid=str(cascade_uuid), dry_run=False, recursive=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["recursive"] is True
    assert payload["data"]["deleted_step_id"] == "T-001"
    assert payload["data"]["deleted_step_ids"] == ["A-001", "T-001"]
    assert calls["delete_subtree"] == TS_UUID
    # Admitted under the cascade: the whole subtree lands in ONE
    # cascade_write_many revision; the direct-mode writer is never used.
    written = calls["cascade_write_many"]
    assert [node_uuid for node_uuid, _snapshot in written["node_changes"]] == [AS_UUID, TS_UUID]
    assert all(snapshot["deleted"] is True for _node_uuid, snapshot in written["node_changes"])
    assert "record_revision" not in calls


def test_recursive_delete_without_frozen_ancestor_is_admitted_directly(monkeypatch) -> None:
    nodes = _tree(gs_status="draft")
    calls = _patch_common(monkeypatch, nodes, open_cascade=None)

    result = asyncio.run(
        StepDeleteCommand().execute(plan="p", step_id="T-001", dry_run=False, recursive=True)
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["recursive"] is True
    assert calls["delete_subtree"] == TS_UUID
    # Direct mode (no cascade anywhere): one record_revision carries every
    # tombstone; the control proves the first test's refusal is caused by
    # the frozen ancestor alone, not by the harness setup.
    assert [node_uuid for node_uuid, _snapshot in calls["record_revision"]["changes"]] == [AS_UUID, TS_UUID]
    assert "cascade_write_many" not in calls
