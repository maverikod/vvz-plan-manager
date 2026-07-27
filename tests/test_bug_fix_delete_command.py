"""Behavioral coverage for BugFixDeleteCommand (todo 9b09c9b0, full CRUD for the
bug family): dry_run preview, soft-delete happy path, hard-delete happy path,
DELETE_BLOCKED, and BUG_FIX_NOT_FOUND.

See tests/test_bug_delete_command.py's module docstring for why this patches
BugFix.crud_reference_counts directly rather than faking the raw
conn.execute() call sequence.
"""
from __future__ import annotations

import asyncio
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from plan_manager.commands import bug_fix_delete_command, plan_completion_guard, runtime_delete_command_helpers
from plan_manager.domain.bug_fix import BugFix

FIX_UUID = uuid.uuid4()
BUG_UUID = uuid.uuid4()
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _bug_fix(**overrides: Any) -> BugFix:
    fields: dict[str, Any] = dict(
        fix_uuid=FIX_UUID,
        bug_uuid=BUG_UUID,
        status="proposed",
        fix_type="code_change",
        summary="a fix attempt used for delete-command tests",
        implementation_notes=None,
        source_project_id=None,
        branch=None,
        commit_hash=None,
        pull_request=None,
        changed_files=None,
        tests=None,
        author="tester",
        reviewer=None,
        started_at=None,
        implemented_at=None,
        verified_at=None,
        verification_method=None,
        expected_result=None,
        actual_result=None,
        passed=None,
        revert_info=None,
        created_by="tester",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        deleted_at=None,
    )
    fields.update(overrides)
    return BugFix(**fields)


@contextmanager
def _fake_db():
    yield object()


def _unbound_bug(bug_uuid: uuid.UUID) -> Any:
    """A minimal stand-in for BugReport carrying only what
    refuse_if_bug_fix_plan_completed reads: a plan-unbound source_plan_uuid."""
    return types.SimpleNamespace(bug_uuid=bug_uuid, source_plan_uuid=None)


def _install_fakes(
    monkeypatch,
    *,
    references: dict[str, int] | None = None,
    get_result: BugFix | None = _bug_fix(),
    soft_delete_result: BugFix | None = None,
) -> None:
    monkeypatch.setattr(runtime_delete_command_helpers, "db_connection", lambda: _fake_db())
    monkeypatch.setattr(bug_fix_delete_command, "get_bug_fix", lambda conn, fix_uuid: get_result)
    monkeypatch.setattr(
        BugFix, "crud_reference_counts", classmethod(lambda cls, conn, entity_id: dict(references or {}))
    )
    # refuse_if_bug_fix_plan_completed derives the PARENT bug's plan anchor via
    # plan_completion_guard's own module-level get_bug (a two-hop bug_fix -> bug
    # -> source_plan_uuid derivation); fake it to a plan-unbound bug so the
    # completion guard is a no-op and tests stay isolated from bug_report_store.
    monkeypatch.setattr(
        plan_completion_guard,
        "get_bug",
        lambda conn, bug_uuid: _unbound_bug(bug_uuid),
    )
    if soft_delete_result is not None:
        monkeypatch.setattr(
            bug_fix_delete_command,
            "soft_delete_bug_fix",
            lambda conn, fix_uuid, *, changed_by: soft_delete_result,
        )


def test_bug_fix_delete_dry_run_on_existing_unreferenced_fix_does_not_raise(monkeypatch) -> None:
    _install_fakes(monkeypatch)

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(
            bug_fix=str(FIX_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_delete"] == str(FIX_UUID)
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["blocked"] is False
    assert payload["data"]["references"] == {}


def test_bug_fix_delete_soft_deletes_existing_unreferenced_fix(monkeypatch) -> None:
    deleted = _bug_fix(deleted_at=NOW.isoformat())
    _install_fakes(monkeypatch, soft_delete_result=deleted)

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(bug_fix=str(FIX_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["bug_fix"]["uuid"] == str(FIX_UUID)
    assert payload["data"]["bug_fix"]["deleted_at"] is not None


def test_bug_fix_delete_hard_deletes_existing_unreferenced_fix(monkeypatch) -> None:
    _install_fakes(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bug_fix_delete_command,
        "hard_delete_bug_fix",
        lambda conn, fix_uuid, *, changed_by: calls.append({"fix_uuid": fix_uuid, "changed_by": changed_by}),
    )

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(
            bug_fix=str(FIX_UUID), changed_by="tester", hard=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["mode"] == "hard"
    assert payload["data"]["deleted_uuid"] == str(FIX_UUID)
    assert calls == [{"fix_uuid": FIX_UUID, "changed_by": "tester"}]


def test_bug_fix_delete_dry_run_reports_blocked_for_live_reference(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"bug_fix_propagation.bug_fix_uuid": 1})

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(
            bug_fix=str(FIX_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"bug_fix_propagation.bug_fix_uuid": 1}


def test_bug_fix_delete_blocked_by_live_reference_refuses_non_dry_run_delete(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"bug_fix_propagation.bug_fix_uuid": 1})

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(bug_fix=str(FIX_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "DELETE_BLOCKED"
    assert payload["error"]["data"]["references"] == {"bug_fix_propagation.bug_fix_uuid": 1}


def test_bug_fix_delete_reports_bug_fix_not_found_for_missing_fix(monkeypatch) -> None:
    _install_fakes(monkeypatch, get_result=None)

    result = asyncio.run(
        bug_fix_delete_command.BugFixDeleteCommand().execute(bug_fix=str(uuid.uuid4()), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "BUG_FIX_NOT_FOUND"
