"""Tests for G-003/T-002 (C-007 FrozenSubtreeMembershipInvariant): while an
ancestor step is frozen, creating a descendant beneath it, moving a step
into or out of it, and deleting any step within it must be admitted only
under an open cascade.

Covers the two closed gaps:
  1. cascade.regime.check_admission / frozen_ancestor: a step whose ANCESTOR
     (not itself, not a descendant) is frozen was previously admitted for
     direct mutation.
  2. step_move: moving a step INTO a frozen (or frozen-ancestor) new_parent
     was previously not admission-checked at all.

Unit-style, no real database: direct calls to check_admission / frozen_ancestor
with constructed node maps (matching tests/test_hotfix_cascade_frozen_guard.py),
plus command-level monkeypatch tests for step_move (matching the established
pattern of tests/test_plan_unfreeze.py and tests/test_step_transition_fast_fail.py).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.cascade import regime as regime_mod
from plan_manager.cascade.record import CascadeError, CascadeRecord
from plan_manager.commands import step_move_command
from plan_manager.commands.step_move_command import StepMoveCommand
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


def _step(step_uuid: str, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=uuid.UUID(step_uuid), plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _grandparent_frozen_tree() -> dict[uuid.UUID, Step]:
    """G-001 (frozen) -> T-001 (draft) -> A-001 (draft).

    T-001 and A-001 are each other's only descendants/ancestor within this
    tree; neither is itself frozen nor has a frozen descendant, but both
    have a frozen ANCESTOR (G-001)."""
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "frozen")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "draft")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "draft")
    return {s.uuid: s for s in (gs, ts, atomic)}


def _all_draft_tree() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "draft")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "draft")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "draft")
    other_gs = _step("00000000-0000-0000-0000-000000000021", 3, "G-002", None, "draft")
    return {s.uuid: s for s in (gs, ts, atomic, other_gs)}


@contextmanager
def _fake_db():
    yield object()


# --------------------------------------------------------------------- frozen_ancestor


def test_frozen_ancestor_true_for_grandchild_of_a_frozen_step() -> None:
    nodes = _grandparent_frozen_tree()
    ts_uuid = uuid.UUID("00000000-0000-0000-0000-000000000012")
    atomic_uuid = uuid.UUID("00000000-0000-0000-0000-000000000013")
    assert regime_mod.frozen_ancestor(nodes, ts_uuid) is True
    assert regime_mod.frozen_ancestor(nodes, atomic_uuid) is True


def test_frozen_ancestor_false_for_the_frozen_step_itself_and_for_an_unrelated_tree() -> None:
    nodes = _grandparent_frozen_tree()
    gs_uuid = uuid.UUID("00000000-0000-0000-0000-000000000011")
    # The frozen step itself has no ANCESTOR that is frozen (it has no
    # ancestor at all): frozen_ancestor inspects strict ancestors only.
    assert regime_mod.frozen_ancestor(nodes, gs_uuid) is False

    all_draft = _all_draft_tree()
    other_gs_uuid = uuid.UUID("00000000-0000-0000-0000-000000000021")
    assert regime_mod.frozen_ancestor(all_draft, other_gs_uuid) is False


def test_frozen_ancestor_raises_for_unknown_uuid() -> None:
    nodes = _all_draft_tree()
    try:
        regime_mod.frozen_ancestor(nodes, uuid.uuid4())
    except CascadeError:
        pass
    else:
        raise AssertionError("expected CascadeError for an unknown origin_uuid")


# --------------------------------------------------------------------- check_admission


def test_check_admission_refuses_a_step_with_a_frozen_ancestor_without_cascade(monkeypatch) -> None:
    nodes = _grandparent_frozen_tree()
    ts_uuid = uuid.UUID("00000000-0000-0000-0000-000000000012")
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    try:
        regime_mod.check_admission(object(), PLAN_UUID, "step", ts_uuid, None)
    except CascadeError:
        pass
    else:
        raise AssertionError("expected CascadeError: T-001 has a frozen ancestor (G-001)")


def test_check_admission_admits_a_step_with_a_frozen_ancestor_under_a_matching_cascade(monkeypatch) -> None:
    nodes = _grandparent_frozen_tree()
    ts_uuid = uuid.UUID("00000000-0000-0000-0000-000000000012")
    rec = CascadeRecord(
        uuid=uuid.uuid4(), plan_uuid=PLAN_UUID, name="cascade/x",
        base_revision_uuid=uuid.uuid4(), status="open",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: rec)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    admitted = regime_mod.check_admission(object(), PLAN_UUID, "step", ts_uuid, rec.uuid)
    assert admitted is rec


def test_check_admission_still_admits_a_step_with_no_frozen_ancestor_directly(monkeypatch) -> None:
    nodes = _all_draft_tree()
    ts_uuid = uuid.UUID("00000000-0000-0000-0000-000000000012")
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    assert regime_mod.check_admission(object(), PLAN_UUID, "step", ts_uuid, None) is None


# --------------------------------------------------------------------- step_move: new_parent side


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = _HEAD_REV


def _patch_move(monkeypatch, nodes) -> dict:
    calls: dict = {}
    monkeypatch.setattr(step_move_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_move_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_move_command, "load_steps", lambda conn, plan_uuid: nodes)
    # check_admission (the real regime.check_admission, unless a test
    # overrides step_move_command.check_admission directly) internally
    # calls regime.get_open_cascade and regime.load_steps, not the
    # step_move_command-level names patched above: patch those too so a
    # direct-mode (no cascade_uuid) call reaches the real admission logic
    # under test without touching a database.
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)
    return calls


def test_step_move_refuses_moving_into_a_frozen_ancestor_subtree_without_cascade(monkeypatch) -> None:
    """T-001 (draft, under frozen G-001) moves under A-001... instead exercise
    the new_parent side directly: move a free-standing draft step under
    T-001, whose ancestor G-001 is frozen. Direct mode (no cascade_uuid)
    must be refused even though neither the moved step nor T-001 itself is
    frozen or has a frozen DESCENDANT."""
    nodes = _grandparent_frozen_tree()
    other_gs = _step("00000000-0000-0000-0000-000000000031", 3, "G-003", None, "draft")
    nodes[other_gs.uuid] = other_gs
    _patch_move(monkeypatch, nodes)

    result = asyncio.run(
        StepMoveCommand().execute(plan="p", step_id="G-003", new_parent_step_id="T-001")
    )
    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "FROZEN_ARTIFACT"


def test_step_move_admits_moving_into_a_frozen_ancestor_subtree_under_cascade(monkeypatch) -> None:
    nodes = _grandparent_frozen_tree()
    movable = _step("00000000-0000-0000-0000-000000000041", 4, "T-099", None, "draft")
    nodes[movable.uuid] = movable
    calls = _patch_move(monkeypatch, nodes)

    cascade_uuid = uuid.uuid4()
    rec = CascadeRecord(
        uuid=cascade_uuid, plan_uuid=PLAN_UUID, name="cascade/x",
        base_revision_uuid=uuid.uuid4(), status="open",
        created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    monkeypatch.setattr(
        step_move_command, "check_admission", lambda conn, pu, kind, target_uuid, cu: rec
    )

    def _fake_move(conn, target_uuid, new_parent_uuid):
        nodes[target_uuid].parent_step_uuid = new_parent_uuid
        return nodes[target_uuid]

    monkeypatch.setattr(step_move_command, "move_step", _fake_move)

    def _cascade_write(conn, plan_uuid, rec_, target_uuid, snapshot, status_updates, actor, message):
        calls["cascade_write"] = True
        return uuid.uuid4()

    monkeypatch.setattr(step_move_command, "cascade_write", _cascade_write)
    monkeypatch.setattr(step_move_command, "get_step", lambda conn, target_uuid: nodes[target_uuid])

    result = asyncio.run(
        StepMoveCommand().execute(
            plan="p", step_id="T-099", new_parent_step_id="T-001", cascade_uuid=str(cascade_uuid)
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert calls.get("cascade_write") is True


def test_step_move_still_admits_a_non_frozen_move_directly(monkeypatch) -> None:
    nodes = _all_draft_tree()
    movable = _step("00000000-0000-0000-0000-000000000099", 4, "T-099", None, "draft")
    nodes[movable.uuid] = movable
    calls = _patch_move(monkeypatch, nodes)

    def _fake_move(conn, target_uuid, new_parent_uuid):
        nodes[target_uuid].parent_step_uuid = new_parent_uuid
        return nodes[target_uuid]

    monkeypatch.setattr(step_move_command, "move_step", _fake_move)

    def _rev(conn, plan_uuid, actor, message, changes, parent, ref_name=None):
        calls["revision"] = True
        return uuid.uuid4()

    monkeypatch.setattr(step_move_command, "record_revision", _rev)
    monkeypatch.setattr(step_move_command, "get_step", lambda conn, target_uuid: nodes[target_uuid])

    result = asyncio.run(
        StepMoveCommand().execute(plan="p", step_id="T-099", new_parent_step_id="G-001")
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert calls.get("revision") is True
