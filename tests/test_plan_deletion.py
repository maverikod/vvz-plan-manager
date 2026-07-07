"""Tests for plan soft/hard deletion and the plan_list show_deleted filter.

Soft delete marks a plan hidden from the default catalog while preserving it
and keeping it resolvable; hard delete removes the plan row permanently
(children cascade in the database). plan_list gains an optional
show_deleted flag and surfaces each plan's bound projects.
"""

import uuid
from datetime import datetime, timezone

import pytest
from mcp_proxy_adapter.core.errors import ValidationError

from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.plan_delete_command import PlanDeleteCommand
from plan_manager.commands.plan_list_command import PlanListCommand
from plan_manager.domain.plan import (
    Plan,
    create_plan,
    hard_delete_plan,
    list_plans,
    soft_delete_plan,
)


class RecordingConn:
    """Records execute() statements; execute() returns a canned cursor."""

    def __init__(self, rows: list | None = None) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self._rows = rows or []

    def execute(self, sql: str, params: tuple = ()):  # noqa: D401
        self.statements.append((sql, params))
        rows = self._rows

        class _Cur:
            def fetchall(self_inner):
                return rows

            def fetchone(self_inner):
                return rows[0] if rows else None

        return _Cur()


# --- domain: dataclass default -------------------------------------------------

def test_new_plan_is_not_deleted() -> None:
    plan = create_plan(RecordingConn(), "my-plan")
    assert plan.deleted_at is None


# --- domain: soft delete -------------------------------------------------------

def test_soft_delete_marks_only_live_rows() -> None:
    conn = RecordingConn()
    plan_uuid = uuid.uuid4()
    soft_delete_plan(conn, plan_uuid)
    sql, params = conn.statements[-1]
    assert "UPDATE plan SET deleted_at = now()" in sql
    # idempotency guard: only stamps rows not already deleted
    assert "deleted_at IS NULL" in sql
    assert params == (plan_uuid,)


# --- domain: hard delete -------------------------------------------------------

def test_hard_delete_removes_the_row() -> None:
    conn = RecordingConn()
    plan_uuid = uuid.uuid4()
    hard_delete_plan(conn, plan_uuid)
    sql, params = conn.statements[-1]
    assert sql.strip().startswith("DELETE FROM plan WHERE uuid")
    assert params == (plan_uuid,)


# --- domain: list filter -------------------------------------------------------

def _row(name: str, deleted: bool):
    return (
        uuid.uuid4(), name, "draft", 4000, None,
        ["4acd4be1-d166-417d-81c6-76bf77b4a392"], None,
        datetime.now(timezone.utc) if deleted else None,
    )


def test_list_plans_hides_deleted_by_default() -> None:
    conn = RecordingConn(rows=[_row("a", False)])
    plans = list_plans(conn)
    sql, _ = conn.statements[-1]
    assert "WHERE deleted_at IS NULL" in sql
    assert plans[0].deleted_at is None
    assert plans[0].project_ids == ["4acd4be1-d166-417d-81c6-76bf77b4a392"]


def test_list_plans_show_deleted_drops_the_filter() -> None:
    conn = RecordingConn(rows=[_row("a", True)])
    plans = list_plans(conn, show_deleted=True)
    sql, _ = conn.statements[-1]
    assert "WHERE deleted_at IS NULL" not in sql
    assert plans[0].deleted_at is not None


# --- command: plan_delete schema & params -------------------------------------

def test_plan_delete_schema_shape() -> None:
    schema = PlanDeleteCommand.get_schema()
    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["hard"]["type"] == "boolean"
    assert schema["properties"]["hard"]["default"] is False


def test_plan_delete_defaults_hard_false_and_strips_plan() -> None:
    params = PlanDeleteCommand().validate_params({"plan": "  my-plan  "})
    assert params["plan"] == "my-plan"
    assert params["hard"] is False


def test_plan_delete_rejects_non_bool_hard() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PlanDeleteCommand().validate_params({"plan": "my-plan", "hard": "yes"})


def test_plan_delete_rejects_empty_plan() -> None:
    with pytest.raises(ValueError):
        PlanDeleteCommand().validate_params({"plan": "   "})


def test_plan_delete_metadata_declares_plan_not_found() -> None:
    meta = PlanDeleteCommand.metadata()
    assert "PLAN_NOT_FOUND" in meta["error_cases"]
    assert set(meta["parameters"]) == {"plan", "hard"}


# --- command: plan_list params ------------------------------------------------

def test_plan_list_defaults_show_deleted_false() -> None:
    params = PlanListCommand().validate_params({})
    assert params["show_deleted"] is False


def test_plan_list_rejects_non_bool_show_deleted() -> None:
    with pytest.raises((ValidationError, ValueError)):
        PlanListCommand().validate_params({"show_deleted": "all"})


# --- info: capability exposure ------------------------------------------------

def test_info_capabilities_describe_plan_lifecycle() -> None:
    caps = InfoCommand._section_data("capabilities", {})
    assert "plan_lifecycle" in caps
    plan_lifecycle = caps["plan_lifecycle"]
    assert set(plan_lifecycle["commands"]["plan_delete"]["modes"]) == {"soft", "hard"}
    assert "PLAN_NOT_FOUND" in plan_lifecycle["domain_errors"]

