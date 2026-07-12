"""Regression test for 0.1.26 hotfix defect 5: malformed-UUID inputs must return a clean
RUNTIME_VALIDATION_ERROR domain code instead of leaking a raw Python ValueError (-32603)."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    block_get_command,
    escalation_resolve_command,
    execution_attempt_get_command,
    project_dependency_discover_command,
    project_dependents_command,
    todo_get_command,
)

BAD_UUID = "not-a-valid-uuid"


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    def __init__(self):
        self.uuid = uuid.uuid4()


def _assert_validation_error(result) -> None:
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_todo_get_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(todo_get_command, "db_connection", _fake_db)
    result = asyncio.run(todo_get_command.TodoGetCommand().execute(todo=BAD_UUID))
    _assert_validation_error(result)


def test_execution_attempt_get_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(execution_attempt_get_command, "db_connection", _fake_db)
    result = asyncio.run(
        execution_attempt_get_command.ExecutionAttemptGetCommand().execute(attempt_id=BAD_UUID)
    )
    _assert_validation_error(result)


def test_block_get_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(block_get_command, "db_connection", _fake_db)
    monkeypatch.setattr(block_get_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    result = asyncio.run(block_get_command.BlockGetCommand().execute(plan="p", block_id=BAD_UUID))
    _assert_validation_error(result)


def test_escalation_resolve_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(escalation_resolve_command, "db_connection", _fake_db)
    monkeypatch.setattr(escalation_resolve_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    result = asyncio.run(
        escalation_resolve_command.EscalationResolveCommand().execute(
            plan="p", escalation_uuid=BAD_UUID, resolved_by="x", resolution="y"
        )
    )
    _assert_validation_error(result)


def test_project_dependents_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(project_dependents_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependents_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    result = asyncio.run(
        project_dependents_command.ProjectDependentsCommand().execute(plan="p", project_id=BAD_UUID)
    )
    _assert_validation_error(result)


def test_project_dependency_discover_rejects_malformed_uuid(monkeypatch) -> None:
    monkeypatch.setattr(project_dependency_discover_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        project_dependency_discover_command, "resolve_plan", lambda conn, plan: _DummyPlan()
    )
    result = asyncio.run(
        project_dependency_discover_command.ProjectDependencyDiscoverCommand().execute(
            plan="p", source_project_id=BAD_UUID
        )
    )
    _assert_validation_error(result)
