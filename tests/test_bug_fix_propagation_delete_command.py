"""Behavioral coverage for BugFixPropagationDeleteCommand (todo 9b09c9b0, full
CRUD for the bug family): dry_run preview, soft-delete happy path, hard-delete
happy path, DELETE_BLOCKED, and BUG_PROPAGATION_NOT_FOUND.

See tests/test_bug_delete_command.py's module docstring for why this patches
BugFixPropagation.crud_reference_counts directly rather than faking the raw
conn.execute() call sequence. Unlike the other three bug-family entities,
BugFixPropagation is a leaf (no domain-specific HARD_DELETE_REFERENCE_CHECKS
and no CENTRAL_REFERENCE_CHECKS["bug_fix_propagation"] entry either) -- the
blocked-path tests here exercise the generic mechanism with a synthetic
reference count rather than a real schema-derived one.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from plan_manager.commands import bug_fix_propagation_delete_command, runtime_delete_command_helpers
from plan_manager.domain.bug_fix_propagation import BugFixPropagation

PROPAGATION_UUID = uuid.uuid4()
BUG_FIX_UUID = uuid.uuid4()
IMPACT_UUID = uuid.uuid4()
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _propagation(**overrides: Any) -> BugFixPropagation:
    fields: dict[str, Any] = dict(
        propagation_uuid=PROPAGATION_UUID,
        bug_fix_uuid=BUG_FIX_UUID,
        impact_uuid=IMPACT_UUID,
        target_type=None,
        target_identifier=None,
        action="no_action_required",
        status="pending",
        assigned_to=None,
        linked_todo_uuid=None,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at=None,
        finished_at=None,
        evidence=None,
        verification_result=None,
        created_by="tester",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        deleted_at=None,
    )
    fields.update(overrides)
    return BugFixPropagation(**fields)


@contextmanager
def _fake_db():
    yield object()


def _install_fakes(
    monkeypatch,
    *,
    references: dict[str, int] | None = None,
    get_result: BugFixPropagation | None = _propagation(),
    soft_delete_result: BugFixPropagation | None = None,
) -> None:
    monkeypatch.setattr(runtime_delete_command_helpers, "db_connection", lambda: _fake_db())
    monkeypatch.setattr(
        bug_fix_propagation_delete_command, "get_bug_fix_propagation", lambda conn, propagation_uuid: get_result
    )
    monkeypatch.setattr(
        BugFixPropagation,
        "crud_reference_counts",
        classmethod(lambda cls, conn, entity_id: dict(references or {})),
    )
    if soft_delete_result is not None:
        monkeypatch.setattr(
            bug_fix_propagation_delete_command,
            "soft_delete_bug_fix_propagation",
            lambda conn, propagation_uuid, *, changed_by: soft_delete_result,
        )


def test_bug_fix_propagation_delete_dry_run_on_existing_unreferenced_propagation_does_not_raise(
    monkeypatch,
) -> None:
    _install_fakes(monkeypatch)

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(PROPAGATION_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_delete"] == str(PROPAGATION_UUID)
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["blocked"] is False
    assert payload["data"]["references"] == {}


def test_bug_fix_propagation_delete_soft_deletes_existing_unreferenced_propagation(monkeypatch) -> None:
    deleted = _propagation(deleted_at=NOW.isoformat())
    _install_fakes(monkeypatch, soft_delete_result=deleted)

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(PROPAGATION_UUID), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["bug_fix_propagation"]["uuid"] == str(PROPAGATION_UUID)
    assert payload["data"]["bug_fix_propagation"]["deleted_at"] is not None


def test_bug_fix_propagation_delete_hard_deletes_existing_unreferenced_propagation(monkeypatch) -> None:
    _install_fakes(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bug_fix_propagation_delete_command,
        "hard_delete_bug_fix_propagation",
        lambda conn, propagation_uuid, *, changed_by: calls.append(
            {"propagation_uuid": propagation_uuid, "changed_by": changed_by}
        ),
    )

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(PROPAGATION_UUID), changed_by="tester", hard=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["mode"] == "hard"
    assert payload["data"]["deleted_uuid"] == str(PROPAGATION_UUID)
    assert calls == [{"propagation_uuid": PROPAGATION_UUID, "changed_by": "tester"}]


def test_bug_fix_propagation_delete_dry_run_reports_blocked_for_live_reference(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"some_table.propagation_uuid": 1})

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(PROPAGATION_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"some_table.propagation_uuid": 1}


def test_bug_fix_propagation_delete_blocked_by_live_reference_refuses_non_dry_run_delete(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"some_table.propagation_uuid": 1})

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(PROPAGATION_UUID), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "DELETE_BLOCKED"
    assert payload["error"]["data"]["references"] == {"some_table.propagation_uuid": 1}


def test_bug_fix_propagation_delete_reports_bug_propagation_not_found_for_missing_propagation(
    monkeypatch,
) -> None:
    _install_fakes(monkeypatch, get_result=None)

    result = asyncio.run(
        bug_fix_propagation_delete_command.BugFixPropagationDeleteCommand().execute(
            propagation_id=str(uuid.uuid4()), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "BUG_PROPAGATION_NOT_FOUND"
