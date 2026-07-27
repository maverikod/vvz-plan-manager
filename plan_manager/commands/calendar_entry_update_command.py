"""Command: update mutable fields of a calendar-based work entry."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import perform_runtime_update
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.storage.calendar_entry_store import get_calendar_entry, update_calendar_entry


class CalendarEntryUpdateCommand(Command):
    name: ClassVar[str] = "calendar_entry_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Update mutable fields of a calendar-based work entry."
    category: ClassVar[str] = "calendar_entry"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "calendar_entry": {"type": "string", "format": "uuid", "description": "Calendar-entry UUID."},
                "changed_by": {"type": "string", "description": "Actor updating the entry."},
                "title": {"type": "string", "description": "New title, if changing."},
                "description": {"type": "string", "description": "New description, if changing."},
                "status": {"type": "string", "description": "New status, if changing."},
                "start_date": {"type": "string", "format": "date", "description": "New inclusive start date, if changing."},
                "end_date": {"type": "string", "format": "date", "description": "New inclusive end date, if changing."},
                "assigned_to": {"type": "string", "description": "New assigned actor, if changing."},
                "wish": {"type": "string", "format": "uuid", "description": "New linked wish UUID, if changing."},
            },
            "required": ["calendar_entry", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "calendar_entry": {"description": "Calendar-entry UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Actor updating the entry.", "type": "string", "required": True},
            "title": {"description": "New title, if changing.", "type": "string", "required": False},
            "description": {"description": "New description, if changing.", "type": "string", "required": False},
            "status": {"description": "New status, if changing.", "type": "string", "required": False},
            "start_date": {"description": "New inclusive start date, if changing.", "type": "string", "required": False},
            "end_date": {"description": "New inclusive end date, if changing.", "type": "string", "required": False},
            "assigned_to": {"description": "New assigned actor, if changing.", "type": "string", "required": False},
            "wish": {"description": "New linked wish UUID, if changing.", "type": "string", "required": False},
        }
        return calendar_entry_metadata(
            cls,
            params,
            {"success": {"description": "The updated CalendarEntry payload."}},
            [{"description": "Move a calendar entry into in-progress status.", "command": {"calendar_entry": "11111111-1111-1111-1111-111111111111", "changed_by": "owner", "status": "in_progress"}}],
            include_not_found=True,
            best_practices=[
                "If either date bound changes, the updated range must still be inclusive and non-negative.",
                "Use the linked wish only when the entry is part of delivering one specific desire; otherwise rely on the primary anchor alone.",
            ],
        )

    async def execute(
        self,
        calendar_entry: str,
        changed_by: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        assigned_to: str | None = None,
        wish: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_update(
                raw_entity_id=calendar_entry,
                get_record=get_calendar_entry,
                update_record=update_calendar_entry,
                changed_by=changed_by,
                not_found_code="CALENDAR_ENTRY_NOT_FOUND",
                not_found_message=f"calendar entry not found: {calendar_entry}",
                update_fields={
                    "title": title,
                    "description": description,
                    "status": status,
                    "start_date": start_date,
                    "end_date": end_date,
                    "assigned_to": assigned_to,
                    "wish_uuid": validate_uuid(wish) if wish is not None else None,
                },
            )
        except Exception as exc:
            return map_exception(exc)
