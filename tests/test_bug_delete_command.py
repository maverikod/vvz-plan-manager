"""Regression/behavioral coverage for BugDeleteCommand (todo 9b09c9b0, full CRUD
for the bug family): dry_run preview, soft-delete happy path, hard-delete happy
path, the DELETE_BLOCKED refusal, and BUG_NOT_FOUND.

Follows the fake-store/connection idiom of tests/test_todo_delete_command.py,
but patches BugReport.crud_reference_counts directly instead of faking the raw
conn.execute() call sequence: plan_manager.domain.entity.CENTRAL_REFERENCE_CHECKS
already defines a "bug" entry (bug_report.py's own duplicate/parent/impact/fix
checks, mirrored) THAT DUPLICATES BugReport.HARD_DELETE_REFERENCE_CHECKS
one-for-one -- find_entity_reference_counts runs both, doubling the SQL-call
count for identical checks. Faking that exact doubled index sequence would be
brittle and would test the duplication artifact, not BugDeleteCommand's own
logic; patching crud_reference_counts at the class level isolates the command
under test from that pre-existing (out of scope) duplication.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from plan_manager.commands import bug_delete_command, runtime_delete_command_helpers
from plan_manager.domain.bug_report import BugReport

BUG_UUID = uuid.uuid4()
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _bug_report(**overrides: Any) -> BugReport:
    fields: dict[str, Any] = dict(
        bug_uuid=BUG_UUID,
        title="scratch bug for delete-command tests",
        short_description="one-liner",
        detailed_description="a bug used to test bug_delete",
        expected_behavior=None,
        actual_behavior=None,
        reproduction=None,
        evidence=None,
        environment=None,
        kind="functional",
        severity="minor",
        priority_nice=50,
        status="reported",
        reporter="tester",
        owner=None,
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type="none",
        source_project_id=None,
        source_file_path=None,
        source_plan_uuid=None,
        source_revision_uuid=None,
        source_step_uuid=None,
        source_step_path=None,
        source_ref_id=None,
        source_command=None,
        source_service=None,
        confirmed_at=None,
        closed_at=None,
        reopened_at=None,
        created_by="tester",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        deleted_at=None,
    )
    fields.update(overrides)
    return BugReport(**fields)


@contextmanager
def _fake_db():
    yield object()  # opaque: no test in this module reaches raw conn.execute()


def _install_fakes(
    monkeypatch,
    *,
    references: dict[str, int] | None = None,
    get_result: BugReport | None = _bug_report(),
    soft_delete_result: BugReport | None = None,
) -> None:
    monkeypatch.setattr(runtime_delete_command_helpers, "db_connection", lambda: _fake_db())
    monkeypatch.setattr(bug_delete_command, "get_bug", lambda conn, bug_uuid: get_result)
    monkeypatch.setattr(
        BugReport, "crud_reference_counts", classmethod(lambda cls, conn, entity_id: dict(references or {}))
    )
    if soft_delete_result is not None:
        monkeypatch.setattr(
            bug_delete_command,
            "soft_delete_bug",
            lambda conn, bug_uuid, *, changed_by: soft_delete_result,
        )


def test_bug_delete_dry_run_on_existing_unreferenced_bug_does_not_raise(monkeypatch) -> None:
    """dry_run=true on an existing, unreferenced bug must preview cleanly."""
    _install_fakes(monkeypatch)

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(
            bug_id=str(BUG_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_delete"] == str(BUG_UUID)
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["blocked"] is False
    assert payload["data"]["references"] == {}


def test_bug_delete_dry_run_hard_mode_reports_hard(monkeypatch) -> None:
    """dry_run=true, hard=true previews mode='hard' without writing."""
    _install_fakes(monkeypatch)

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(
            bug_id=str(BUG_UUID), changed_by="tester", dry_run=True, hard=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["mode"] == "hard"


def test_bug_delete_soft_deletes_existing_unreferenced_bug(monkeypatch) -> None:
    """The non-dry-run happy path on an existing, unreferenced bug soft-deletes it."""
    deleted = _bug_report(deleted_at=NOW.isoformat())
    _install_fakes(monkeypatch, soft_delete_result=deleted)

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(bug_id=str(BUG_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["bug"]["bug_uuid"] == str(BUG_UUID)
    assert payload["data"]["bug"]["deleted_at"] is not None


def test_bug_delete_hard_deletes_existing_unreferenced_bug(monkeypatch) -> None:
    """hard=true on an existing, unreferenced bug calls hard_delete_bug and reports deleted_uuid."""
    _install_fakes(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bug_delete_command,
        "hard_delete_bug",
        lambda conn, bug_uuid, *, changed_by: calls.append({"bug_uuid": bug_uuid, "changed_by": changed_by}),
    )

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(bug_id=str(BUG_UUID), changed_by="tester", hard=True)
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "hard"
    assert payload["data"]["deleted_uuid"] == str(BUG_UUID)
    assert calls == [{"bug_uuid": BUG_UUID, "changed_by": "tester"}]


def test_bug_delete_dry_run_reports_blocked_for_live_reference(monkeypatch) -> None:
    """A live inbound reference must be reported in dry_run, never swallowed."""
    _install_fakes(monkeypatch, references={"bug_impact.bug_uuid": 2})

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(
            bug_id=str(BUG_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"bug_impact.bug_uuid": 2}


def test_bug_delete_blocked_by_live_reference_refuses_non_dry_run_delete(monkeypatch) -> None:
    """Outside dry_run, a live reference must refuse the deletion with DELETE_BLOCKED."""
    _install_fakes(monkeypatch, references={"bug_impact.bug_uuid": 2})

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(bug_id=str(BUG_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "DELETE_BLOCKED"
    assert payload["error"]["data"]["references"] == {"bug_impact.bug_uuid": 2}


def test_bug_delete_reports_bug_not_found_for_missing_bug(monkeypatch) -> None:
    """A nonexistent bug reports BUG_NOT_FOUND, not a raw exception."""
    _install_fakes(monkeypatch, get_result=None)

    result = asyncio.run(
        bug_delete_command.BugDeleteCommand().execute(bug_id=str(uuid.uuid4()), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "BUG_NOT_FOUND"
