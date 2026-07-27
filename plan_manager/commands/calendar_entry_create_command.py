"""Command: create a calendar-entry work item."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_work_command_helpers import (
    build_primary_anchor,
    primary_anchor_metadata_params,
    primary_anchor_schema_properties,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.calendar_entry_store import create_calendar_entry


class CalendarEntryCreateCommand(Command):
    name: ClassVar[str] = "calendar_entry_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a calendar-based work entry spanning one or more calendar days."
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
                "title": {"type": "string", "description": "Calendar entry title."},
                "description": {"type": "string", "description": "Calendar entry description."},
                "status": {"type": "string", "description": "Initial status (planned, in_progress, done, cancelled)."},
                "start_date": {"type": "string", "format": "date", "description": "Inclusive start date (YYYY-MM-DD)."},
                "end_date": {"type": "string", "format": "date", "description": "Inclusive end date (YYYY-MM-DD)."},
                "created_by": {"type": "string", "description": "Actor creating the entry."},
                "assigned_to": {"type": "string", "description": "Actor expected to perform the scheduled work."},
                "wish": {"type": "string", "format": "uuid", "description": "Optional linked wish UUID."},
                **primary_anchor_schema_properties(),
            },
            "required": ["title", "description", "status", "start_date", "end_date", "created_by", "anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "title": {"description": "Calendar entry title.", "type": "string", "required": True},
            "description": {"description": "Calendar entry description.", "type": "string", "required": True},
            "status": {"description": "Initial status (planned, in_progress, done, cancelled).", "type": "string", "required": True},
            "start_date": {"description": "Inclusive start date (YYYY-MM-DD).", "type": "string", "required": True},
            "end_date": {"description": "Inclusive end date (YYYY-MM-DD).", "type": "string", "required": True},
            "created_by": {"description": "Actor creating the entry.", "type": "string", "required": True},
            "assigned_to": {"description": "Actor expected to perform the scheduled work.", "type": "string", "required": False},
            "wish": {"description": "Optional linked wish UUID.", "type": "string", "required": False},
            **primary_anchor_metadata_params(),
        }
        return calendar_entry_metadata(
            cls,
            params,
            {"success": {"description": "The created CalendarEntry payload."}},
            [{
                "description": "Create a two-day implementation window for a project step.",
                "command": {
                    "title": "Implement calendar CRUD",
                    "description": "Add the calendar-entry data layer and command surface.",
                    "status": "planned",
                    "start_date": "2026-07-27",
                    "end_date": "2026-07-28",
                    "created_by": "owner",
                    "anchor_type": "step",
                    "anchor_plan_uuid": "11111111-1111-1111-1111-111111111111",
                    "anchor_step_uuid": "22222222-2222-2222-2222-222222222222",
                },
            }],
            best_practices=[
                "Use calendar entries for dated work windows, not for abstract intent; the linked wish (if any) captures the desire, while the calendar entry captures the scheduled span.",
                "start_date and end_date are inclusive calendar-day bounds; multi-day windows are valid as long as end_date is not earlier than start_date.",
            ],
        )

    async def execute(
        self,
        title: str,
        description: str,
        status: str,
        start_date: str,
        end_date: str,
        created_by: str,
        anchor_type: str,
        assigned_to: str | None = None,
        wish: str | None = None,
        anchor_project_id: str | None = None,
        anchor_file_path: str | None = None,
        anchor_plan_uuid: str | None = None,
        anchor_revision_uuid: str | None = None,
        anchor_step_uuid: str | None = None,
        anchor_step_path: str | None = None,
        anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            anchor = build_primary_anchor(
                anchor_type=anchor_type,
                anchor_project_id=anchor_project_id,
                anchor_file_path=anchor_file_path,
                anchor_plan_uuid=anchor_plan_uuid,
                anchor_revision_uuid=anchor_revision_uuid,
                anchor_step_uuid=anchor_step_uuid,
                anchor_step_path=anchor_step_path,
                anchor_ref_id=anchor_ref_id,
            )
            with db_connection() as conn:
                record = create_calendar_entry(
                    conn,
                    title=title,
                    description=description,
                    status=status,
                    start_date=start_date,
                    end_date=end_date,
                    created_by=created_by,
                    anchor=anchor,
                    assigned_to=assigned_to,
                    wish_uuid=validate_uuid(wish) if wish is not None else None,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
