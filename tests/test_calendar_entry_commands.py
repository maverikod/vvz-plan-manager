"""Command-level coverage for the calendar-entry CRUD surface."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import uuid

from plan_manager.commands import calendar_entry_create_command, calendar_entry_get_command, calendar_entry_list_command, calendar_entry_update_command
from plan_manager.commands import runtime_record_command_helpers
from plan_manager.commands.calendar_entry_create_command import CalendarEntryCreateCommand
from plan_manager.commands.calendar_entry_get_command import CalendarEntryGetCommand
from plan_manager.commands.calendar_entry_list_command import CalendarEntryListCommand
from plan_manager.commands.calendar_entry_update_command import CalendarEntryUpdateCommand
from plan_manager.domain.calendar_entry import CalendarEntry


@contextmanager
def _fake_db():
    yield object()


def _entry(**overrides) -> CalendarEntry:
    fields = {
        "calendar_entry_uuid": uuid.UUID("22222222-2222-2222-2222-222222222222"),
        "title": "Implement CRUD",
        "description": "Build the wish and calendar-entry data layer.",
        "status": "planned",
        "start_date": "2026-07-27",
        "end_date": "2026-07-28",
        "created_by": "owner",
        "assigned_to": "agent",
        "wish_uuid": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "created_at": "2026-07-26T00:00:00+00:00",
        "updated_at": "2026-07-26T00:00:00+00:00",
        "primary_anchor_type": "none",
        "anchor_project_id": None,
        "anchor_file_path": None,
        "anchor_plan_uuid": None,
        "anchor_revision_uuid": None,
        "anchor_step_uuid": None,
        "anchor_step_path": None,
        "anchor_ref_id": None,
        "deleted_at": None,
    }
    fields.update(overrides)
    return CalendarEntry(**fields)


def test_calendar_entry_create_returns_created_payload(monkeypatch) -> None:
    created = _entry()
    monkeypatch.setattr(calendar_entry_create_command, "db_connection", _fake_db)
    monkeypatch.setattr(calendar_entry_create_command, "create_calendar_entry", lambda conn, **kwargs: created)

    result = asyncio.run(
        CalendarEntryCreateCommand().execute(
            title="Implement CRUD",
            description="Build the wish and calendar-entry data layer.",
            status="planned",
            start_date="2026-07-27",
            end_date="2026-07-28",
            created_by="owner",
            anchor_type="none",
            wish="11111111-1111-1111-1111-111111111111",
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["calendar_entry_uuid"] == str(created.calendar_entry_uuid)


def test_calendar_entry_list_returns_uniform_page_envelope(monkeypatch) -> None:
    monkeypatch.setattr(calendar_entry_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        calendar_entry_list_command,
        "list_calendar_entries_page",
        lambda conn, **kwargs: ([_entry()], 1),
    )

    result = asyncio.run(
        CalendarEntryListCommand().execute(
            day_from="2026-07-27",
            day_to="2026-07-28",
            wish="11111111-1111-1111-1111-111111111111",
            limit=10,
            offset=0,
        )
    ).to_dict()

    assert result["success"] is True
    data = result["data"]
    assert set(data) == {"calendar_entries", "total", "limit", "offset"}
    assert data["total"] == 1
    assert data["limit"] == 10
    assert data["offset"] == 0


def test_calendar_entry_get_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(runtime_record_command_helpers, "db_connection", _fake_db)
    monkeypatch.setattr(calendar_entry_get_command, "get_calendar_entry", lambda conn, entry_uuid: _entry())

    result = asyncio.run(
        CalendarEntryGetCommand().execute("22222222-2222-2222-2222-222222222222")
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["calendar_entry_uuid"] == "22222222-2222-2222-2222-222222222222"


def test_calendar_entry_update_returns_updated_payload(monkeypatch) -> None:
    monkeypatch.setattr(runtime_record_command_helpers, "db_connection", _fake_db)
    monkeypatch.setattr(calendar_entry_update_command, "get_calendar_entry", lambda conn, entry_uuid: _entry())
    monkeypatch.setattr(
        calendar_entry_update_command,
        "update_calendar_entry",
        lambda conn, entry_uuid, **kwargs: _entry(status=kwargs["status"]),
    )

    result = asyncio.run(
        CalendarEntryUpdateCommand().execute(
            calendar_entry="22222222-2222-2222-2222-222222222222",
            changed_by="owner",
            status="in_progress",
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["status"] == "in_progress"
