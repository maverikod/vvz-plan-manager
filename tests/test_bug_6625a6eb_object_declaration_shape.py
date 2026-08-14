"""Regression tests for bug 6625a6eb: level-5 object declarations must be
validated on write, while legacy stored string declarations must not crash
the object inventory read-path.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from plan_manager.cascade import regime as regime_mod
from plan_manager.commands import step_update_command
from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.domain.step import Step
from plan_manager.exchange import layout_import
from plan_manager.maintenance.step_objects_normalize import (
    persist_step_object_rewrites,
    plan_step_object_rewrites,
)
from plan_manager.views.objects import object_inventory


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000006625a6")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-000000662500")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-000000662501")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-000000662502")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-000000662503")


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REVISION


@contextmanager
def _fake_db():
    yield object()


def _gs_step() -> Step:
    return Step(
        uuid=GS_UUID,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=None,
        level=3,
        step_id="G-001",
        slug="scratch-gs",
        fields={},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _ts_step() -> Step:
    return Step(
        uuid=TS_UUID,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=GS_UUID,
        level=4,
        step_id="T-001",
        slug="scratch-ts",
        fields={},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _as_step(fields: dict) -> Step:
    return Step(
        uuid=AS_UUID,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=TS_UUID,
        level=5,
        step_id="A-001",
        slug="scratch-as",
        fields=fields,
        depends_on=[],
        concepts=["C-001"],
        project_id=None,
        status="draft",
    )


def _nodes(as_fields: dict) -> dict[uuid.UUID, Step]:
    gs = _gs_step()
    ts = _ts_step()
    atomic = _as_step(as_fields)
    return {step.uuid: step for step in (gs, ts, atomic)}


def _patch_common(monkeypatch, nodes: dict[uuid.UUID, Step]) -> dict:
    calls: dict = {}
    monkeypatch.setattr(step_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_update_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_update_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_update_command, "list_concept_ids", lambda conn, plan_uuid: ["C-001"])
    monkeypatch.setattr(regime_mod, "get_open_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(regime_mod, "load_steps", lambda conn, plan_uuid: nodes)

    def _update_step_fields_and_concepts(conn, target_uuid, merged_fields, new_concepts):
        calls["update_step_fields_and_concepts"] = dict(merged_fields)

    monkeypatch.setattr(
        step_update_command, "update_step_fields_and_concepts", _update_step_fields_and_concepts
    )

    def _record_revision(conn, plan_uuid, actor, message, changes, parent_revision_uuid, ref_name=None, **_kwargs):
        calls["record_revision"] = changes
        return uuid.UUID("00000000-0000-0000-0000-0000006625ff")

    monkeypatch.setattr(step_update_command, "record_revision", _record_revision)

    def _get_step(conn, target_uuid):
        merged = calls.get("update_step_fields_and_concepts")
        fields = merged if merged is not None else nodes[target_uuid].fields
        return _as_step(fields)

    monkeypatch.setattr(step_update_command, "get_step", _get_step)
    return calls


def test_invalid_as_object_write_rejected_atomically(monkeypatch) -> None:
    nodes = _nodes({"target_file": "pkg/widget.py", "objects": []})
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepUpdateCommand().execute(
            plan="p",
            step_id="A-001",
            fields={"objects": ["Widget"]},
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_STEP_FIELD_SHAPE"
    assert "objects[0] must be an object" in payload["error"]["message"]
    assert "update_step_fields_and_concepts" not in calls
    assert "record_revision" not in calls


def test_valid_as_object_write_still_works(monkeypatch) -> None:
    nodes = _nodes({"target_file": "pkg/widget.py", "objects": []})
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepUpdateCommand().execute(
            plan="p",
            step_id="A-001",
            fields={"objects": [{"name": "Widget", "concepts": ["C-001"]}]},
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["fields"]["objects"] == [{"name": "Widget", "concepts": ["C-001"]}]
    assert "update_step_fields_and_concepts" in calls
    assert "record_revision" in calls


def test_layout_import_rejects_malformed_as_objects_at_both_boundaries(tmp_path: Path) -> None:
    as_dir = tmp_path / "atomic_steps"
    as_dir.mkdir()
    descriptor = as_dir / "A-001-scratch-as.yaml"
    descriptor.write_text(
        "step_id: A-001\n"
        "target_file: pkg/widget.py\n"
        "objects:\n"
        "  - Widget\n",
        encoding="utf-8",
    )

    issues = layout_import.validate_as_file(descriptor)
    assert issues == [f"{descriptor}: objects[0] must be an object"]

    with pytest.raises(ValueError) as excinfo:
        layout_import._create_step_from_descriptor(
            object(),
            PLAN_UUID,
            descriptor,
            "A-001-scratch-as",
            5,
            TS_UUID,
        )
    assert "invalid AS objects item shape" in str(excinfo.value)
    assert "objects[0] must be an object" in str(excinfo.value)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _InventoryConn:
    def execute(self, query: str, params=()):
        assert params == (PLAN_UUID,), params
        if "level = 3" in query:
            return _Rows([(GS_UUID, "G-001")])
        if "level = 4" in query:
            return _Rows([(TS_UUID, GS_UUID, "T-001")])
        if "level = 5" in query:
            return _Rows(
                [
                    (
                        TS_UUID,
                        "A-001",
                        {"target_file": "pkg/widget.py", "objects": ["Widget"]},
                        ["C-001"],
                    )
                ]
            )
        raise AssertionError(query)


def test_object_inventory_coerces_legacy_string_declarations() -> None:
    inventory = object_inventory(_InventoryConn(), PLAN_UUID)

    assert set(inventory) == {"Widget"}
    assert inventory["Widget"]["artifact_paths"] == ["G-001/T-001/A-001"]
    assert inventory["Widget"]["declared_concepts"] == []
    assert inventory["Widget"]["as_concepts"] == ["C-001"]


def test_plan_step_object_rewrites_reports_convertible_legacy_rows() -> None:
    nodes = _nodes({"target_file": "pkg/widget.py", "objects": ["Widget"]})
    rewrites, invalid_steps = plan_step_object_rewrites(
        nodes,
        lambda step: "G-001/T-001/A-001",
    )

    assert invalid_steps == []
    assert [rewrite.path for rewrite in rewrites] == ["G-001/T-001/A-001"]
    assert rewrites[0].fields["objects"] == [
        {"name": "Widget", "concepts": []}
    ]


def test_plan_step_object_rewrites_reports_non_convertible_shapes() -> None:
    nodes = _nodes({"target_file": "pkg/widget.py", "objects": [{"name": "", "concepts": []}]})
    rewrites, invalid_steps = plan_step_object_rewrites(
        nodes,
        lambda step: "G-001/T-001/A-001",
    )

    assert rewrites == []
    assert invalid_steps == [
        {
            "path": "G-001/T-001/A-001",
            "problems": [
                {
                    "field_name": "objects",
                    "index": 0,
                    "message": "objects[0].name must be a non-empty string",
                }
            ],
        }
    ]


def test_persist_step_object_rewrites_writes_one_revision(monkeypatch) -> None:
    nodes = _nodes({"target_file": "pkg/widget.py", "objects": ["Widget"]})
    rewrites, invalid_steps = plan_step_object_rewrites(
        nodes,
        lambda step: "G-001/T-001/A-001",
    )
    assert invalid_steps == []
    calls: dict[str, Any] = {}

    def _update_step_fields(conn, step_uuid, fields):
        calls.setdefault("update_step_fields", {})[step_uuid] = dict(fields)

    def _record_revision(conn, plan_uuid, author, message, changes, parent_revision_uuid, ref_name):
        calls["record_revision"] = {
            "plan_uuid": plan_uuid,
            "author": author,
            "message": message,
            "changes": changes,
            "parent_revision_uuid": parent_revision_uuid,
            "ref_name": ref_name,
        }
        return uuid.UUID("00000000-0000-0000-0000-0000006626ff")

    monkeypatch.setattr(
        "plan_manager.maintenance.step_objects_normalize.update_step_fields",
        _update_step_fields,
    )
    monkeypatch.setattr(
        "plan_manager.maintenance.step_objects_normalize.record_revision",
        _record_revision,
    )

    revision_uuid = persist_step_object_rewrites(
        object(),
        PLAN_UUID,
        rewrites,
        parent_revision_uuid=HEAD_REVISION,
        ref_name=None,
        author="api",
        message="step_objects_normalize: 1 step(s)",
    )

    assert revision_uuid == uuid.UUID("00000000-0000-0000-0000-0000006626ff")
    assert calls["update_step_fields"][AS_UUID]["objects"] == [
        {"name": "Widget", "concepts": []}
    ]
    assert calls["record_revision"]["message"] == "step_objects_normalize: 1 step(s)"
    assert calls["record_revision"]["parent_revision_uuid"] == HEAD_REVISION
    assert calls["record_revision"]["ref_name"] is None
    assert calls["record_revision"]["changes"][0][1]["fields"]["objects"] == [
        {"name": "Widget", "concepts": []}
    ]
