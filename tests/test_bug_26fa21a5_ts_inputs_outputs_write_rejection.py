"""Regression tests for bug 26fa21a5-5487-4cf7-9b41-64a350a7074c.

Parent bug ad529347 fixed the DOCUMENTATION gap: help/context field_schema
now publish the nested TS inputs/outputs item contract ({name, type,
description}, type one of "input" or "output"). This child bug closes the
ENFORCEMENT gap that documentation gap made easy to hit: step_update
persisted an invalid TS payload (plain strings, or objects with a missing
or out-of-enum field) verbatim, advanced the working revision, staled
previously-current context blocks, and let descendant context bundles
still be compiled from the invalid TS -- only a later plan_validate run
reported parse.inputs_outputs findings.

The fix (plan_manager.domain.step.validate_ts_inputs_outputs, the single
shared validator) is proven live against the deployed 0.1.53 server
in this task's own investigation (see the bug report and orchestrator
report); these tests pin the same contract at the unit level, matching
the established db-mocking pattern of
tests/test_cr4_integration_frozen_recursive_delete.py (no real database:
monkeypatch db_connection/resolve_plan/load_steps on the command module
and get_open_cascade/load_steps on cascade.regime; the real check_admission
runs unmocked).

Six properties are proven:
    1. An invalid step_update write is rejected atomically with a precise
       INVALID_STEP_FIELD_SHAPE error, and no write function is ever
       reached (test_invalid_write_rejected_atomically_with_precise_error).
    2. Because no revision is recorded, the plan's head revision is
       unchanged, so any context block stored at that (untouched) revision
       stays current -- has_current_common_block is a pure function of
       stored vs. working revision_uuid, proven directly here
       (test_rejected_write_leaves_context_blocks_current).
    3. A valid write still works and the revision advances
       (test_valid_write_still_works_and_revision_advances).
    4. layout_import rejects the same malformed shapes at both the
       pre-flight (validate_descriptor_dir) and write-time
       (_create_step_from_descriptor) boundaries
       (test_layout_import_rejects_malformed_ts_inputs_outputs_at_both_boundaries).
    5. context_common refuses to compile a child-level bundle from a
       structurally invalid TS parent
       (test_context_common_refuses_invalid_ts_parent).
    6. The mechanical gate now enforces the type enum, not just
       non-empty-string shape (test_gate_enforces_type_enum), matching
       tests/test_bug_ad529347_ts_inputs_outputs_schema.py's
       test_gate_inputs_outputs_now_rejects_out_of_enum_type.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.cascade import regime as regime_mod
from plan_manager.commands import step_update_command
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.domain.step import Step
from plan_manager.exchange import layout_import
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_structure import check_parse_inputs_outputs
from plan_manager.views import context_blocks
from plan_manager.views.context_blocks import has_current_common_block


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000021")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000022")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000000023")


class _DummyPlan:
    """Minimal Plan stand-in carrying only what step_update reads."""

    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REVISION


@contextmanager
def _fake_db():
    """Fake db_connection() yielding an opaque connection object.

    Every function that would otherwise use the connection is itself
    monkeypatched by _patch_common, so the yielded object is never
    dereferenced.
    """
    yield object()


def _gs_step() -> Step:
    """Build the level-3 (GS) parent of the scratch TS used by every test."""
    return Step(
        uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
        step_id="G-001", slug="scratch-gs", fields={}, depends_on=[],
        concepts=[], project_id=None, status="draft",
    )


def _ts_step(fields: dict) -> Step:
    """Build the level-4 (TS) step under test, carrying the given fields."""
    return Step(
        uuid=TS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=GS_UUID, level=4,
        step_id="T-001", slug="scratch-ts", fields=fields, depends_on=[],
        concepts=[], project_id=None, status="draft",
    )


def _nodes(ts_fields: dict) -> dict[uuid.UUID, Step]:
    gs = _gs_step()
    ts = _ts_step(ts_fields)
    return {gs.uuid: gs, ts.uuid: ts}


def _patch_common(monkeypatch, nodes: dict[uuid.UUID, Step]) -> dict:
    """Wire step_update_command.execute() to run against a fake DB seam.

    Only the database boundary is faked (db_connection, resolve_plan,
    load_steps, list_concept_ids, and the two cascade.regime seams
    get_open_cascade/load_steps); the real check_admission and the real
    validate_ts_inputs_outputs-based rejection run unmocked, exactly as
    tests/test_cr4_integration_frozen_recursive_delete.py does for
    step_delete.

    Returns:
        A dict mutated by the write-boundary spies below; presence of a
        key proves that write function was reached.
    """
    calls: dict = {}
    monkeypatch.setattr(step_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_update_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_update_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_update_command, "list_concept_ids", lambda conn, plan_uuid: [])
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    def _update_step_fields_and_concepts(conn, target_uuid, merged_fields, new_concepts):
        calls["update_step_fields_and_concepts"] = dict(merged_fields)

    monkeypatch.setattr(
        step_update_command, "update_step_fields_and_concepts", _update_step_fields_and_concepts
    )

    def _record_revision(conn, plan_uuid, actor, message, changes, parent_revision_uuid, ref_name=None):
        calls["record_revision"] = changes
        return uuid.UUID("00000000-0000-0000-0000-0000000000ff")

    monkeypatch.setattr(step_update_command, "record_revision", _record_revision)

    def _get_step(conn, target_uuid):
        merged = calls.get("update_step_fields_and_concepts")
        fields = merged if merged is not None else nodes[target_uuid].fields
        return Step(
            uuid=target_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=GS_UUID, level=4,
            step_id="T-001", slug="scratch-ts", fields=fields, depends_on=[],
            concepts=[], project_id=None, status="draft",
        )

    monkeypatch.setattr(step_update_command, "get_step", _get_step)
    return calls


# --------------------------------------------------------------------------
# 1 & 2. Invalid write: atomic rejection, no revision, context stays current.
# --------------------------------------------------------------------------


def test_invalid_write_rejected_atomically_with_precise_error(monkeypatch) -> None:
    nodes = _nodes({"inputs": [], "outputs": [], "name": "t", "description": "d"})
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepUpdateCommand().execute(
            plan="p",
            step_id="T-001",
            fields={"inputs": ["source-file-path"], "outputs": ["parsed-record-list"]},
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_STEP_FIELD_SHAPE"
    message = payload["error"]["message"]
    assert "inputs[0] must be an object" in message
    assert "outputs[0] must be an object" in message
    # Atomicity: neither write function was ever reached.
    assert "update_step_fields_and_concepts" not in calls
    assert "record_revision" not in calls


def test_rejected_write_leaves_context_blocks_current() -> None:
    """No revision recorded (proven above) means the plan's
    head_revision_uuid is unchanged; has_current_common_block is a pure
    function of stored vs. working (revision_uuid, cascade_uuid) (see
    tests/test_context_blocks_currency.py), so a block stored at that
    untouched head revision is still reported current."""

    class _FakeConn:
        def execute(self, sql, params):
            _plan_uuid, _node_path, _child_level, revision_uuid, cascade_uuid = params

            class _Row:
                def fetchone(self_inner):
                    if revision_uuid == HEAD_REVISION and cascade_uuid is None:
                        return (1,)
                    return None

            return _Row()

    assert (
        has_current_common_block(_FakeConn(), PLAN_UUID, "G-001/T-001", 5, HEAD_REVISION, None)
        is True
    )


# --------------------------------------------------------------------------
# 3. Valid write still works and the revision advances.
# --------------------------------------------------------------------------


def test_valid_write_still_works_and_revision_advances(monkeypatch) -> None:
    nodes = _nodes({"inputs": [], "outputs": [], "name": "t", "description": "d"})
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepUpdateCommand().execute(
            plan="p",
            step_id="T-001",
            fields={
                "inputs": [
                    {"name": "source-file-path", "type": "input", "description": "Path to the file being read."}
                ],
                "outputs": [
                    {"name": "parsed-record-list", "type": "output", "description": "Records parsed from the source file."}
                ],
            },
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["fields"]["inputs"][0]["type"] == "input"
    assert payload["data"]["fields"]["outputs"][0]["type"] == "output"
    assert "update_step_fields_and_concepts" in calls
    assert "record_revision" in calls


# --------------------------------------------------------------------------
# 4. layout_import rejects the same malformed shapes.
# --------------------------------------------------------------------------


def test_layout_import_rejects_malformed_ts_inputs_outputs_at_both_boundaries(tmp_path) -> None:
    ts_dir = tmp_path / "T-001-scratch-ts"
    ts_dir.mkdir()
    readme = ts_dir / "README.yaml"
    readme.write_text(
        "step_id: T-001\n"
        "name: scratch\n"
        "description: d\n"
        'inputs: ["source-file-path"]\n'
        "outputs: []\n",
        encoding="utf-8",
    )

    # (a) pre-flight, dry-run-safe validate_layout pass.
    issues = layout_import.validate_descriptor_dir(ts_dir, "T")
    assert any("inputs[0] must be an object" in issue for issue in issues)

    # (b) write-time defense inside _create_step_from_descriptor, right
    # before create_step would otherwise be called; conn/plan_uuid are
    # never dereferenced because the rejection happens first.
    with pytest.raises(ValueError, match=r"inputs\[0\] must be an object"):
        layout_import._create_step_from_descriptor(
            conn=None,
            plan_uuid=None,
            descriptor_path=readme,
            name=ts_dir.name,
            level=4,
            parent_step_uuid=None,
        )


# --------------------------------------------------------------------------
# 5. context_common refuses to compile from a structurally invalid parent.
# --------------------------------------------------------------------------


def test_context_common_refuses_invalid_ts_parent(monkeypatch) -> None:
    nodes = _nodes({"inputs": ["source-file-path"], "outputs": [], "name": "t", "description": "d"})
    monkeypatch.setattr(context_blocks, "load_steps", lambda conn, plan_uuid: nodes)

    with pytest.raises(DomainCommandError) as excinfo:
        context_blocks.common_context(object(), PLAN_UUID, "T-001", 5)

    assert excinfo.value.code == "PARENT_STEP_INVALID"
    assert "G-001/T-001" in excinfo.value.message
    assert "inputs[0] must be an object" in excinfo.value.message


# --------------------------------------------------------------------------
# 6. The mechanical gate enforces the type enum, not just non-empty shape.
# --------------------------------------------------------------------------


def test_gate_enforces_type_enum() -> None:
    step = _ts_step({"inputs": [{"name": "a", "type": "bogus", "description": "d"}], "outputs": []})
    tree = GateTree(steps={step.uuid: step}, concept_ids=[], relations=[], labels=[], counts={})

    findings = check_parse_inputs_outputs(tree, [step])

    assert len(findings) == 1
    assert 'must be one of "input" or "output"' in findings[0].message
    assert "bogus" in findings[0].message
