"""Tests for plan_manager.commands.step_list_command."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.commands.step_list_command import (
    StepListCommand,
    _build_entry,
    _matches_filters,
    _project,
)
from plan_manager.commands.step_list_schema import get_step_list_schema
from plan_manager.domain.step import Step


def _step(
    *,
    uuid_val: uuid.UUID,
    parent_step_uuid: uuid.UUID | None,
    level: int,
    step_id: str,
    slug: str,
    fields: dict | None = None,
    depends_on: list[str] | None = None,
    concepts: list[str] | None = None,
    project_id: str | None = None,
    status: str = "draft",
) -> Step:
    """Build a Step instance directly, with no database access."""
    return Step(
        uuid=uuid_val,
        plan_uuid=uuid.uuid4(),
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=slug,
        fields=fields if fields is not None else {},
        depends_on=depends_on if depends_on is not None else [],
        concepts=concepts if concepts is not None else [],
        project_id=project_id,
        status=status,
    )


def _tree() -> tuple[dict[uuid.UUID, Step], Step, Step]:
    """Build a two-level in-memory step tree: one global step and one tactical child."""
    g_uuid = uuid.uuid4()
    t_uuid = uuid.uuid4()
    g = _step(
        uuid_val=g_uuid,
        parent_step_uuid=None,
        level=3,
        step_id="G-002",
        slug="surface",
    )
    t = _step(
        uuid_val=t_uuid,
        parent_step_uuid=g_uuid,
        level=4,
        step_id="T-001",
        slug="step-list-surface",
    )
    nodes = {g_uuid: g, t_uuid: t}
    return nodes, g, t


def test_build_entry_full_fields() -> None:
    """_build_entry returns every full-step-field key for a level-4 step."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert set(entry.keys()) == {
        "uuid",
        "step_id",
        "slug",
        "level",
        "project_id",
        "status",
        "parent_path",
        "parent_uuid",
        "fields",
        "depends_on",
        "concepts",
        "path",
        "artifact_path",
    }
    assert entry["uuid"] == str(t.uuid)
    assert entry["path"] == "G-002/T-001"
    assert entry["parent_uuid"] == str(g.uuid)


def test_matches_filters_level() -> None:
    """_matches_filters rejects an entry whose level does not equal the requested level filter."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert (
        _matches_filters(
            entry, level=4, parent_uuid_filter=None, status=None, target_file=None
        )
        is True
    )
    assert (
        _matches_filters(
            entry, level=3, parent_uuid_filter=None, status=None, target_file=None
        )
        is False
    )


def test_matches_filters_parent_uuid() -> None:
    """_matches_filters rejects an entry whose parent_uuid does not equal the requested parent filter."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=str(g.uuid),
            status=None,
            target_file=None,
        )
        is True
    )
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=str(uuid.uuid4()),
            status=None,
            target_file=None,
        )
        is False
    )


def test_matches_filters_status() -> None:
    """_matches_filters rejects an entry whose status does not equal the requested status filter."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=None,
            status="draft",
            target_file=None,
        )
        is True
    )
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=None,
            status="frozen",
            target_file=None,
        )
        is False
    )


def test_matches_filters_target_file() -> None:
    """_matches_filters rejects an entry whose fields.target_file does not equal the requested target_file filter."""
    g_uuid = uuid.uuid4()
    t_uuid = uuid.uuid4()
    g = _step(uuid_val=g_uuid, parent_step_uuid=None, level=3, step_id="G-002", slug="surface")
    t = _step(
        uuid_val=t_uuid,
        parent_step_uuid=g_uuid,
        level=4,
        step_id="T-001",
        slug="step-list-surface",
        fields={"target_file": "plan_manager/foo.py"},
    )
    nodes = {g_uuid: g, t_uuid: t}
    entry = _build_entry(nodes, t)
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=None,
            status=None,
            target_file="plan_manager/foo.py",
        )
        is True
    )
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=None,
            status=None,
            target_file="other.py",
        )
        is False
    )


def test_matches_filters_target_file_absent() -> None:
    """_matches_filters rejects a step with no fields.target_file when target_file filter is given."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert (
        _matches_filters(
            entry,
            level=None,
            parent_uuid_filter=None,
            status=None,
            target_file="plan_manager/foo.py",
        )
        is False
    )


def test_project_none_returns_entry_unchanged() -> None:
    """_project returns the entry itself when field_names is None."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    assert _project(entry, None) is entry


def test_project_keeps_only_requested_keys() -> None:
    """_project returns only the requested keys, ignoring keys not present in field_names."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    result = _project(entry, ["uuid", "step_id"])
    assert result == {"uuid": entry["uuid"], "step_id": entry["step_id"]}
    assert set(result.keys()) == {"uuid", "step_id"}


def test_project_ignores_unknown_key_name() -> None:
    """_project silently ignores a field_names entry that is not among the entry's own keys."""
    nodes, g, t = _tree()
    entry = _build_entry(nodes, t)
    result = _project(entry, ["uuid", "totally_unknown_key"])
    assert result == {"uuid": entry["uuid"]}


def test_get_schema_shape() -> None:
    """get_schema returns a strict JSON-schema with plan required and additionalProperties False."""
    schema = get_step_list_schema()
    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["level"]["enum"] == [3, 4, 5]
    assert schema["properties"]["status"]["enum"] == [
        "draft",
        "ready_for_review",
        "frozen",
        "needs_review",
        "in_progress",
        "done",
    ]
    for prop_name, prop_dict in schema["properties"].items():
        assert "type" in prop_dict, f"Property {prop_name} missing 'type'"
        assert "description" in prop_dict, f"Property {prop_name} missing 'description'"


def test_get_schema_delegates_to_schema_module() -> None:
    """StepListCommand.get_schema() returns exactly what get_step_list_schema() builds."""
    assert StepListCommand.get_schema() == get_step_list_schema()


def test_validate_params_accepts_known_projection() -> None:
    """validate_params returns params unchanged when the fields projection names only real entry keys."""
    cmd = StepListCommand()
    result = cmd.validate_params({"plan": "x", "fields": ["uuid", "step_id"]})
    assert result["fields"] == ["uuid", "step_id"]


def test_validate_params_rejects_unknown_projection_key() -> None:
    """validate_params raises ValueError when the fields projection names an unknown entry key."""
    cmd = StepListCommand()
    with pytest.raises(ValueError):
        cmd.validate_params({"plan": "x", "fields": ["nonexistent_key"]})
