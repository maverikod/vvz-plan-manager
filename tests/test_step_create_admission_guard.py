"""Tests for the context-block admission guard wired into step_create (C-002):
step_create refuses to create a level-4 or level-5 child under a parent
lacking a current context_common block for the child level, and proceeds
normally once the guard passes. Guard wiring added by CR-4 G-001/T-001 in
plan_manager/commands/step_create_command.py.

All tests are unit-style with the established monkeypatch _fake_db / fake-conn
pattern (no real database), matching tests/test_plan_unfreeze.py and
tests/test_step_transition_command.py. The currency derivation itself
(current_working_state, has_current_common_block) is unit-tested separately
in tests/test_context_blocks_currency.py; here both are monkeypatched as
black boxes to isolate the step_create wiring under test.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import step_create_command
from plan_manager.commands.step_create_command import StepCreateCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000011")


@contextmanager
def _fake_db():
    yield object()


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


def _gs_tree() -> dict[uuid.UUID, Step]:
    gs = Step(
        uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None,
        level=3, step_id="G-001", slug="g-001", fields={},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )
    return {gs.uuid: gs}


def _new_step(step_id: str = "T-001") -> Step:
    return Step(
        uuid=uuid.uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=GS_UUID,
        level=4, step_id=step_id, slug=step_id.lower(), fields={},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )


def _patch_common(monkeypatch, *, has_common_block: bool) -> dict:
    calls: dict = {}
    nodes = _gs_tree()
    monkeypatch.setattr(step_create_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_create_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_create_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_create_command, "check_admission",
        lambda conn, plan_uuid, kind, target_uuid, cascade_uuid: None,
    )
    monkeypatch.setattr(
        step_create_command, "current_working_state",
        lambda conn, plan: (HEAD_REV, None),
    )

    def _has_common(conn, plan_uuid, node_path, level, revision, cascade):
        calls["guard_query"] = (node_path, level, revision, cascade)
        return has_common_block

    monkeypatch.setattr(step_create_command, "has_current_common_block", _has_common)

    new_step = _new_step()

    def _create_step(conn, plan_uuid, parent_uuid, level, slug, fields, deps, concepts, project_id):
        calls["created"] = True
        return new_step

    monkeypatch.setattr(step_create_command, "create_step", _create_step)
    monkeypatch.setattr(step_create_command, "get_step", lambda conn, step_uuid: new_step)
    monkeypatch.setattr(
        step_create_command, "record_revision",
        lambda conn, plan_uuid, author, message, changes, parent_rev, ref_name: uuid.uuid4(),
    )
    return calls


def test_step_create_refuses_child_without_current_common_block(monkeypatch) -> None:
    calls = _patch_common(monkeypatch, has_common_block=False)

    result = asyncio.run(
        StepCreateCommand().execute(plan="p", level=4, slug="graph-commands", parent_step_id="G-001")
    )
    payload = result.to_dict()

    assert payload["error"]["data"]["domain_code"] == "CONTEXT_BLOCKS_MISSING"
    assert payload["error"]["data"]["node"] == "G-001"
    assert payload["error"]["data"]["child_level"] == 4
    assert calls["guard_query"] == ("G-001", 4, HEAD_REV, None)
    assert "created" not in calls


def test_step_create_proceeds_when_common_block_is_current(monkeypatch) -> None:
    calls = _patch_common(monkeypatch, has_common_block=True)

    result = asyncio.run(
        StepCreateCommand().execute(plan="p", level=4, slug="graph-commands", parent_step_id="G-001")
    )
    payload = result.to_dict()

    assert payload["success"] is True
    assert calls["created"] is True


def test_step_create_skips_guard_for_level_3_root_step(monkeypatch) -> None:
    calls = _patch_common(monkeypatch, has_common_block=False)

    result = asyncio.run(
        StepCreateCommand().execute(plan="p", level=3, slug="new-global-step")
    )
    payload = result.to_dict()

    assert payload["success"] is True
    assert "guard_query" not in calls
    assert calls["created"] is True
