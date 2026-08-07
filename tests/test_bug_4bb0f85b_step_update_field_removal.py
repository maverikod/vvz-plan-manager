"""Regression tests for bug 4bb0f85b (registry, anchored to a step):
step_update could not remove a key from fields -- passing {"key": null}
inside the fields payload merged the null in via plain dict.update
semantics, so the key survived in stored fields with a null value instead
of being removed. There was no way to delete a stored fields key.

The fix is plan_manager.commands.step_update_command._merge_step_fields:
an explicit null (JSON null / Python None) for a key in the fields patch
now pops that key from the merged mapping; nulling an absent key is a
no-op; every other key is merged exactly as before (shallow, non-null
values overwrite wholesale). This file proves, at the unit level and via
the same db-mocking harness as
tests/test_bug_26fa21a5_ts_inputs_outputs_write_rejection.py (no real
database: monkeypatch db_connection/resolve_plan/load_steps on the
command module and get_open_cascade/load_steps on cascade.regime; the
real check_admission runs unmocked):

    1. _merge_step_fields unit behavior: null removes an existing key,
       null on an absent key is a no-op, non-null keys are unaffected.
    2. End-to-end via StepUpdateCommand.execute(): nulling a key through
       the fields payload removes it from the persisted/re-read fields,
       other keys survive untouched.
    3. Frozen-truth protection is unchanged: step_update on a frozen step
       still refuses with FROZEN_ARTIFACT, and the merge/write path is
       never reached, whether or not the payload contains a null.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.cascade import regime as regime_mod
from plan_manager.commands import step_update_command
from plan_manager.commands.step_update_command import StepUpdateCommand, _merge_step_fields
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000031")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000dd")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000032")


class _DummyPlan:
    """Minimal Plan stand-in carrying only what step_update reads."""

    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REVISION


@contextmanager
def _fake_db():
    """Fake db_connection() yielding an opaque connection object; every
    function that would dereference it is itself monkeypatched below."""
    yield object()


def _gs_step(fields: dict, status: str = "draft") -> Step:
    """Build the level-3 (GS) scratch step under test; level 3 carries no
    inputs/outputs or objects schema, so its fields merge is exercised
    without any level-specific shape validation getting in the way."""
    return Step(
        uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
        step_id="G-001", slug="scratch-gs", fields=fields, depends_on=[],
        concepts=[], project_id=None, status=status,
    )


def _patch_common(monkeypatch, step: Step) -> dict:
    """Wire step_update_command.execute() to run against a fake DB seam,
    mirroring tests/test_bug_26fa21a5_ts_inputs_outputs_write_rejection.py:
    only the database boundary is faked; the real check_admission (and,
    for frozen steps, the real frozen_at_or_below path) runs unmocked.

    Returns:
        A dict mutated by the write-boundary spies; presence of a key
        proves that write function was reached. calls["fields_after"]
        tracks the get_step-visible fields after any write.
    """
    nodes = {step.uuid: step}
    calls: dict = {"fields_after": dict(step.fields)}
    monkeypatch.setattr(step_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_update_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_update_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_update_command, "list_concept_ids", lambda conn, plan_uuid: [])
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    def _update_step_fields_and_concepts(conn, target_uuid, merged_fields, new_concepts):
        calls["update_step_fields_and_concepts"] = dict(merged_fields)
        calls["fields_after"] = dict(merged_fields)

    monkeypatch.setattr(
        step_update_command, "update_step_fields_and_concepts", _update_step_fields_and_concepts
    )

    def _record_revision(conn, plan_uuid, actor, message, changes, parent_revision_uuid, ref_name=None):
        calls["record_revision"] = changes
        return uuid.UUID("00000000-0000-0000-0000-0000000000ee")

    monkeypatch.setattr(step_update_command, "record_revision", _record_revision)

    def _get_step(conn, target_uuid):
        return Step(
            uuid=target_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
            step_id="G-001", slug="scratch-gs", fields=dict(calls["fields_after"]),
            depends_on=[], concepts=[], project_id=None, status=step.status,
        )

    monkeypatch.setattr(step_update_command, "get_step", _get_step)
    return calls


# --------------------------------------------------------------------------
# 1. _merge_step_fields unit behavior.
# --------------------------------------------------------------------------


def test_merge_step_fields_null_removes_existing_key() -> None:
    merged = _merge_step_fields({"a": 1, "b": 2}, {"b": None})

    assert merged == {"a": 1}


def test_merge_step_fields_null_on_absent_key_is_noop() -> None:
    merged = _merge_step_fields({"a": 1}, {"missing": None})

    assert merged == {"a": 1}


def test_merge_step_fields_non_null_keys_overwrite_as_before() -> None:
    merged = _merge_step_fields({"a": 1, "b": 2}, {"a": 3, "c": 4})

    assert merged == {"a": 3, "b": 2, "c": 4}


def test_merge_step_fields_mixed_patch_removes_and_overwrites_together() -> None:
    merged = _merge_step_fields({"a": 1, "b": 2, "c": 3}, {"b": None, "c": 30, "d": 4})

    assert merged == {"a": 1, "c": 30, "d": 4}


# --------------------------------------------------------------------------
# 2. End-to-end via StepUpdateCommand.execute().
# --------------------------------------------------------------------------


def test_step_update_null_removes_key_end_to_end(monkeypatch) -> None:
    step = _gs_step({"name": "scratch", "scratch_note": "delete me"})
    calls = _patch_common(monkeypatch, step)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="G-001", fields={"scratch_note": None})
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert "scratch_note" not in payload["data"]["fields"]
    assert payload["data"]["fields"]["name"] == "scratch"
    assert "update_step_fields_and_concepts" in calls
    assert "scratch_note" not in calls["update_step_fields_and_concepts"]


def test_step_update_null_on_absent_key_is_noop_end_to_end(monkeypatch) -> None:
    step = _gs_step({"name": "scratch"})
    calls = _patch_common(monkeypatch, step)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="G-001", fields={"never_set": None})
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["fields"] == {"name": "scratch"}
    assert "update_step_fields_and_concepts" in calls


def test_step_update_other_keys_survive_a_null_patch(monkeypatch) -> None:
    step = _gs_step({"name": "scratch", "description": "keep me", "scratch_note": "drop me"})
    calls = _patch_common(monkeypatch, step)

    result = asyncio.run(
        StepUpdateCommand().execute(
            plan="p", step_id="G-001", fields={"scratch_note": None, "description": "still here"}
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["fields"] == {"name": "scratch", "description": "still here"}
    assert "scratch_note" not in calls["update_step_fields_and_concepts"]


# --------------------------------------------------------------------------
# 3. Frozen-truth protection is unchanged.
# --------------------------------------------------------------------------


def test_step_update_frozen_step_refuses_with_null_patch(monkeypatch) -> None:
    step = _gs_step({"name": "scratch", "scratch_note": "keep or drop, doesn't matter"}, status="frozen")
    calls = _patch_common(monkeypatch, step)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="G-001", fields={"scratch_note": None})
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "FROZEN_ARTIFACT"
    assert "update_step_fields_and_concepts" not in calls
    assert "record_revision" not in calls


def test_step_update_frozen_step_refuses_same_as_a_plain_patch(monkeypatch) -> None:
    """Same frozen refusal fires for an ordinary (non-null) patch, proving
    the fix did not touch the admission/frozen-refusal path at all."""
    step = _gs_step({"name": "scratch"}, status="frozen")
    calls = _patch_common(monkeypatch, step)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="G-001", fields={"name": "renamed"})
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "FROZEN_ARTIFACT"
    assert "update_step_fields_and_concepts" not in calls
