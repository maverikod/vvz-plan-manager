"""Regression tests for todo a5ec9c1a: extend the optional-`plan` pattern
(bug 3eec33f2, shipped 0.1.64 for the 12 bug/bug_fix-family commands) to the
bug_impact_* and bug_propagation_* command groups.

Before this fix, bug_impact_add/update/discover and
bug_propagation_create/update/generate_todos all declared a mandatory
`plan: str` schema parameter and unconditionally called
resolve_plan_guarded(conn, plan) even though every one of these commands
already addresses its mutation target directly by the entity's own UUID
(bug_id / impact_uuid / bug_fix_id / impact_id / propagation_id) and already
had the correct completion guard wired via
plan_manager.commands.plan_completion_guard (refuse_if_bug_plan_completed /
refuse_if_bug_impact_plan_completed / refuse_if_bug_fix_plan_completed /
refuse_if_bug_fix_propagation_plan_completed). An unrelated completed plan
could therefore block a project-anchored bug's impact/propagation records
for no reason. Fix: `plan` becomes `str | None = None` on all six commands;
`resolve_plan` is now called only `if plan is not None`, exactly mirroring
the reference idiom in bug_fix_create_command.py / bug_confirm_command.py.

Pure unit tests (monkeypatched db_connection / fake psycopg-shaped
connections), matching this repo's established style -- see
tests/test_bug_32755092_append_and_3eec33f2_optional_plan.py, which these
tests are written to stay consistent with (same _Entity idiom, same three
cases per command: plan omitted -> success; plan supplied -> old behavior
preserved; completed UNRELATED plan supplied -> PLAN_COMPLETED refused as
before).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands import (
    bug_impact_add_command,
    bug_impact_discover_command,
    bug_impact_update_command,
    bug_propagation_create_command,
    bug_propagation_generate_todos_command,
    bug_propagation_update_command,
    plan_completion_guard,
)
from plan_manager.commands.errors import DomainCommandError


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _fake_db_ctx(conn):
    yield conn


class _Entity:
    """Generic attribute bag standing in for any domain dataclass; matches
    the idiom in tests/test_bug_32755092_append_and_3eec33f2_optional_plan.py
    and tests/test_bug_c3950b83_plan_completed_lock.py."""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def to_payload(self) -> dict:
        return {"uuid": "stub"}


def _never_resolve_plan(conn, plan):
    raise AssertionError(f"resolve_plan must not be called when plan is omitted, got plan={plan!r}")


def _raise_plan_completed(conn, plan):
    raise DomainCommandError("PLAN_COMPLETED", f"plan {plan} is marked completed")


# ---------------------------------------------------------------------------
# bug_impact_add
# ---------------------------------------------------------------------------


def test_bug_impact_add_admits_project_anchored_bug_without_plan(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_add_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_add_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_impact_add_command, "check_row_exists", lambda conn, table, uuid_value, allowed_tables: None)
    monkeypatch.setattr(bug_impact_add_command, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(
        bug_impact_add_command, "create_bug_impact",
        lambda conn, **kwargs: _Entity(to_payload=lambda: {"uuid": "impact-1"}),
    )

    cmd = bug_impact_add_command.BugImpactAddCommand()
    result = _run(
        cmd.execute(
            bug_id=str(uuid.uuid4()), target_type="project", impact_type="uses_broken_api", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_impact_add_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_impact_add_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_add_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_impact_add_command, "check_row_exists", lambda conn, table, uuid_value, allowed_tables: None)
    monkeypatch.setattr(bug_impact_add_command, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(
        bug_impact_add_command, "create_bug_impact",
        lambda conn, **kwargs: _Entity(to_payload=lambda: {"uuid": "impact-1"}),
    )

    cmd = bug_impact_add_command.BugImpactAddCommand()
    result = _run(
        cmd.execute(
            plan="my-plan", bug_id=str(uuid.uuid4()), target_type="project",
            impact_type="uses_broken_api", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_impact_add_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_add_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_add_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_impact_add_command.BugImpactAddCommand()
    result = _run(
        cmd.execute(
            plan="completed-plan", bug_id=str(uuid.uuid4()), target_type="project",
            impact_type="uses_broken_api", created_by="alice",
        )
    )

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# bug_impact_update
# ---------------------------------------------------------------------------


def test_bug_impact_update_admits_without_plan(monkeypatch) -> None:
    impact = _Entity(target_plan_uuid=None, status="suspected", reason=None, skip_decided_by=None)

    monkeypatch.setattr(bug_impact_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_update_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_impact_update_command, "get_bug_impact", lambda conn, impact_id: impact)
    monkeypatch.setattr(
        bug_impact_update_command, "update_bug_impact",
        lambda conn, impact_id, **kwargs: _Entity(to_payload=lambda: {"uuid": str(impact_id)}),
    )

    cmd = bug_impact_update_command.BugImpactUpdateCommand()
    result = _run(cmd.execute(impact_uuid=str(uuid.uuid4()), changed_by="tester", status="confirmed"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_impact_update_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    impact = _Entity(target_plan_uuid=None, status="suspected", reason=None, skip_decided_by=None)
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_impact_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_update_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_impact_update_command, "get_bug_impact", lambda conn, impact_id: impact)
    monkeypatch.setattr(
        bug_impact_update_command, "update_bug_impact",
        lambda conn, impact_id, **kwargs: _Entity(to_payload=lambda: {"uuid": str(impact_id)}),
    )

    cmd = bug_impact_update_command.BugImpactUpdateCommand()
    result = _run(cmd.execute(plan="my-plan", impact_uuid=str(uuid.uuid4()), changed_by="tester", status="confirmed"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_impact_update_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_update_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_impact_update_command.BugImpactUpdateCommand()
    result = _run(cmd.execute(plan="completed-plan", impact_uuid=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# bug_impact_discover
# ---------------------------------------------------------------------------


def test_bug_impact_discover_admits_project_anchored_bug_without_plan(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_discover_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_discover_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_impact_discover_command, "check_row_exists", lambda conn, table, uuid_value, allowed_tables: None)
    monkeypatch.setattr(bug_impact_discover_command, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(bug_impact_discover_command, "discover_suspected_targets", lambda conn, source_uuid: [])

    cmd = bug_impact_discover_command.BugImpactDiscoverCommand()
    result = _run(
        cmd.execute(
            bug_id=str(uuid.uuid4()), source_project_id=str(uuid.uuid4()),
            impact_type="needs_pull", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_impact_discover_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_impact_discover_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_discover_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_impact_discover_command, "check_row_exists", lambda conn, table, uuid_value, allowed_tables: None)
    monkeypatch.setattr(bug_impact_discover_command, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(bug_impact_discover_command, "discover_suspected_targets", lambda conn, source_uuid: [])

    cmd = bug_impact_discover_command.BugImpactDiscoverCommand()
    result = _run(
        cmd.execute(
            plan="my-plan", bug_id=str(uuid.uuid4()), source_project_id=str(uuid.uuid4()),
            impact_type="needs_pull", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_impact_discover_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_discover_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_impact_discover_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_impact_discover_command.BugImpactDiscoverCommand()
    result = _run(
        cmd.execute(
            plan="completed-plan", bug_id=str(uuid.uuid4()), source_project_id=str(uuid.uuid4()),
            impact_type="needs_pull", created_by="alice",
        )
    )

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# bug_propagation_create
# ---------------------------------------------------------------------------


def test_bug_propagation_create_admits_without_plan(monkeypatch) -> None:
    fix_record = _Entity(bug_uuid=uuid.uuid4())

    monkeypatch.setattr(bug_propagation_create_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_create_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_fix", lambda conn, bug_fix_uuid: fix_record)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_impact", lambda conn, impact_uuid: _Entity())
    monkeypatch.setattr(
        bug_propagation_create_command, "create_bug_fix_propagation",
        lambda conn, **kwargs: _Entity(to_payload=lambda: {"uuid": "prop-1"}),
    )
    monkeypatch.setattr(bug_propagation_create_command, "recompute_bug_status", lambda conn, bug_uuid, **kwargs: None)

    cmd = bug_propagation_create_command.BugPropagationCreateCommand()
    result = _run(
        cmd.execute(
            bug_fix_id=str(uuid.uuid4()), impact_id=str(uuid.uuid4()), action="rebuild_package", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_propagation_create_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    fix_record = _Entity(bug_uuid=uuid.uuid4())
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_propagation_create_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_create_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_fix", lambda conn, bug_fix_uuid: fix_record)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_impact", lambda conn, impact_uuid: _Entity())
    monkeypatch.setattr(
        bug_propagation_create_command, "create_bug_fix_propagation",
        lambda conn, **kwargs: _Entity(to_payload=lambda: {"uuid": "prop-1"}),
    )
    monkeypatch.setattr(bug_propagation_create_command, "recompute_bug_status", lambda conn, bug_uuid, **kwargs: None)

    cmd = bug_propagation_create_command.BugPropagationCreateCommand()
    result = _run(
        cmd.execute(
            plan="my-plan", bug_fix_id=str(uuid.uuid4()), impact_id=str(uuid.uuid4()),
            action="rebuild_package", created_by="alice",
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_propagation_create_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_propagation_create_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_create_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_propagation_create_command.BugPropagationCreateCommand()
    result = _run(
        cmd.execute(
            plan="completed-plan", bug_fix_id=str(uuid.uuid4()), impact_id=str(uuid.uuid4()),
            action="rebuild_package", created_by="alice",
        )
    )

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# bug_propagation_update
# ---------------------------------------------------------------------------


def test_bug_propagation_update_admits_without_plan(monkeypatch) -> None:
    propagation = _Entity(linked_plan_uuid=None, bug_fix_uuid=uuid.uuid4(), status="pending")

    monkeypatch.setattr(bug_propagation_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_update_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_propagation_update_command, "get_bug_fix_propagation", lambda conn, propagation_uuid: propagation)
    monkeypatch.setattr(
        bug_propagation_update_command, "update_bug_fix_propagation",
        lambda conn, propagation_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(propagation_uuid)}),
    )
    monkeypatch.setattr(bug_propagation_update_command, "get_bug_fix", lambda conn, bug_fix_uuid: None)

    cmd = bug_propagation_update_command.BugPropagationUpdateCommand()
    result = _run(cmd.execute(propagation_id=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_propagation_update_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    propagation = _Entity(linked_plan_uuid=None, bug_fix_uuid=uuid.uuid4(), status="pending")
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_propagation_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_update_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_propagation_update_command, "get_bug_fix_propagation", lambda conn, propagation_uuid: propagation)
    monkeypatch.setattr(
        bug_propagation_update_command, "update_bug_fix_propagation",
        lambda conn, propagation_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(propagation_uuid)}),
    )
    monkeypatch.setattr(bug_propagation_update_command, "get_bug_fix", lambda conn, bug_fix_uuid: None)

    cmd = bug_propagation_update_command.BugPropagationUpdateCommand()
    result = _run(cmd.execute(plan="my-plan", propagation_id=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_propagation_update_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_propagation_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_update_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_propagation_update_command.BugPropagationUpdateCommand()
    result = _run(cmd.execute(plan="completed-plan", propagation_id=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# bug_propagation_generate_todos
# ---------------------------------------------------------------------------


def test_bug_propagation_generate_todos_admits_without_plan(monkeypatch) -> None:
    monkeypatch.setattr(bug_propagation_generate_todos_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_generate_todos_command, "resolve_plan", _never_resolve_plan)
    monkeypatch.setattr(bug_propagation_generate_todos_command, "get_bug_fix", lambda conn, bug_fix_uuid: None)
    monkeypatch.setattr(
        bug_propagation_generate_todos_command, "list_bug_fix_propagations",
        lambda conn, bug_fix_uuid, status: [],
    )

    cmd = bug_propagation_generate_todos_command.BugPropagationGenerateTodosCommand()
    result = _run(cmd.execute(bug_fix_id=str(uuid.uuid4()), created_by="alice"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert result.data == {"generated": []}


def test_bug_propagation_generate_todos_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    captured: dict = {}

    def fake_resolve_plan(conn, plan):
        captured["plan"] = plan

    monkeypatch.setattr(bug_propagation_generate_todos_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_generate_todos_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(bug_propagation_generate_todos_command, "get_bug_fix", lambda conn, bug_fix_uuid: None)
    monkeypatch.setattr(
        bug_propagation_generate_todos_command, "list_bug_fix_propagations",
        lambda conn, bug_fix_uuid, status: [],
    )

    cmd = bug_propagation_generate_todos_command.BugPropagationGenerateTodosCommand()
    result = _run(cmd.execute(plan="my-plan", bug_fix_id=str(uuid.uuid4()), created_by="alice"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["plan"] == "my-plan"


def test_bug_propagation_generate_todos_with_completed_unrelated_plan_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(bug_propagation_generate_todos_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_propagation_generate_todos_command, "resolve_plan", _raise_plan_completed)

    cmd = bug_propagation_generate_todos_command.BugPropagationGenerateTodosCommand()
    result = _run(cmd.execute(plan="completed-plan", bug_fix_id=str(uuid.uuid4()), created_by="alice"))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"
