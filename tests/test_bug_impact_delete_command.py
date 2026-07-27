"""Behavioral coverage for BugImpactDeleteCommand (todo 9b09c9b0, full CRUD for
the bug family): dry_run preview, soft-delete happy path, hard-delete happy
path, DELETE_BLOCKED, and BUG_IMPACT_NOT_FOUND.

See tests/test_bug_delete_command.py's module docstring for why this patches
BugImpact.crud_reference_counts directly rather than faking the raw
conn.execute() call sequence.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from plan_manager.commands import bug_impact_delete_command, runtime_delete_command_helpers
from plan_manager.domain.bug_impact import BugImpact

IMPACT_UUID = uuid.uuid4()
BUG_UUID = uuid.uuid4()
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _bug_impact(**overrides: Any) -> BugImpact:
    fields: dict[str, Any] = dict(
        impact_uuid=IMPACT_UUID,
        bug_uuid=BUG_UUID,
        target_type="project",
        target_project_id=None,
        target_file_path=None,
        target_plan_uuid=None,
        target_revision_uuid=None,
        target_step_uuid=None,
        target_step_path=None,
        target_ref_id=None,
        target_identifier="some-target",
        impact_type="unknown",
        status="suspected",
        reason=None,
        skip_decided_by=None,
        discovery_method=None,
        resolution_evidence=None,
        created_by="tester",
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        resolved_at=None,
        deleted_at=None,
    )
    fields.update(overrides)
    return BugImpact(**fields)


@contextmanager
def _fake_db():
    yield object()


def _install_fakes(
    monkeypatch,
    *,
    references: dict[str, int] | None = None,
    get_result: BugImpact | None = _bug_impact(),
    soft_delete_result: BugImpact | None = None,
) -> None:
    monkeypatch.setattr(runtime_delete_command_helpers, "db_connection", lambda: _fake_db())
    monkeypatch.setattr(bug_impact_delete_command, "get_bug_impact", lambda conn, impact_uuid: get_result)
    monkeypatch.setattr(
        BugImpact, "crud_reference_counts", classmethod(lambda cls, conn, entity_id: dict(references or {}))
    )
    if soft_delete_result is not None:
        monkeypatch.setattr(
            bug_impact_delete_command,
            "soft_delete_bug_impact",
            lambda conn, impact_uuid, *, changed_by: soft_delete_result,
        )


def test_bug_impact_delete_dry_run_on_existing_unreferenced_impact_does_not_raise(monkeypatch) -> None:
    _install_fakes(monkeypatch)

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(IMPACT_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_delete"] == str(IMPACT_UUID)
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["blocked"] is False
    assert payload["data"]["references"] == {}


def test_bug_impact_delete_soft_deletes_existing_unreferenced_impact(monkeypatch) -> None:
    deleted = _bug_impact(deleted_at=NOW.isoformat())
    _install_fakes(monkeypatch, soft_delete_result=deleted)

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(IMPACT_UUID), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["bug_impact"]["uuid"] == str(IMPACT_UUID)
    assert payload["data"]["bug_impact"]["deleted_at"] is not None


def test_bug_impact_delete_hard_deletes_existing_unreferenced_impact(monkeypatch) -> None:
    _install_fakes(monkeypatch)
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        bug_impact_delete_command,
        "hard_delete_bug_impact",
        lambda conn, impact_uuid, *, changed_by: calls.append(
            {"impact_uuid": impact_uuid, "changed_by": changed_by}
        ),
    )

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(IMPACT_UUID), changed_by="tester", hard=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["mode"] == "hard"
    assert payload["data"]["deleted_uuid"] == str(IMPACT_UUID)
    assert calls == [{"impact_uuid": IMPACT_UUID, "changed_by": "tester"}]


def test_bug_impact_delete_dry_run_reports_blocked_for_live_reference(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"bug_fix_propagation.impact_uuid": 1})

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(IMPACT_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"bug_fix_propagation.impact_uuid": 1}


def test_bug_impact_delete_blocked_by_live_reference_refuses_non_dry_run_delete(monkeypatch) -> None:
    _install_fakes(monkeypatch, references={"bug_fix_propagation.impact_uuid": 1})

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(IMPACT_UUID), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "DELETE_BLOCKED"
    assert payload["error"]["data"]["references"] == {"bug_fix_propagation.impact_uuid": 1}


def test_bug_impact_delete_reports_bug_impact_not_found_for_missing_impact(monkeypatch) -> None:
    _install_fakes(monkeypatch, get_result=None)

    result = asyncio.run(
        bug_impact_delete_command.BugImpactDeleteCommand().execute(
            impact_uuid=str(uuid.uuid4()), changed_by="tester"
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "BUG_IMPACT_NOT_FOUND"
