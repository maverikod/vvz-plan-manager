"""Command: move a calendar entry's primary anchor to a new target, with an audit record (group-3 fix, bug 2c568c0c)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.anchor_confirmation import confirm_anchor
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.reanchor_command_metadata import REANCHOR_BEST_PRACTICES, REANCHOR_ERROR_CASES
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.storage.calendar_entry_store import get_calendar_entry
from plan_manager.storage.entity_reanchor_store import reanchor_owner_form_entity


class CalendarEntryReanchorCommand(Command):
    name: ClassVar[str] = "calendar_entry_reanchor"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a calendar entry's primary anchor to a new target, with an audit record."
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
                "calendar_entry": {"type": "string", "format": "uuid", "description": "Calendar-entry UUID to re-anchor."},
                "changed_by": {"type": "string", "description": "Actor performing this re-anchor move, for audit."},
                "new_anchor_type": {"type": "string", "description": "The candidate new primary anchor kind: none, project, file, plan, revision, step, execution_attempt, review_result, bug, bug_fix, or todo."},
                "new_anchor_project_id": {"type": "string", "format": "uuid", "description": "Project UUID; required when new_anchor_type is project or file."},
                "new_anchor_file_path": {"type": "string", "description": "Project-relative file path; required when new_anchor_type is file."},
                "new_anchor_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID; required when new_anchor_type is plan or step."},
                "new_anchor_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID; required when new_anchor_type is revision (optionally supplied alongside step)."},
                "new_anchor_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID; required when new_anchor_type is step."},
                "new_anchor_step_path": {"type": "string", "description": "Step path, optionally supplied alongside new_anchor_step_uuid."},
                "new_anchor_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID; required when new_anchor_type is execution_attempt, review_result, bug, bug_fix, or todo."},
            },
            "required": ["calendar_entry", "changed_by", "new_anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return calendar_entry_metadata(
            cls,
            params,
            {"success": {"description": "The re-anchored CalendarEntry payload."}},
            [{"description": "Move a calendar entry's anchor to a step.", "command": {"calendar_entry": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "new_anchor_type": "step", "new_anchor_plan_uuid": "22222222-2222-2222-2222-222222222222", "new_anchor_step_uuid": "33333333-3333-3333-3333-333333333333"}}],
            error_cases=REANCHOR_ERROR_CASES,
            best_practices=REANCHOR_BEST_PRACTICES,
        )

    _UUID_FIELDS: ClassVar[tuple[str, ...]] = (
        "calendar_entry", "new_anchor_project_id", "new_anchor_plan_uuid",
        "new_anchor_revision_uuid", "new_anchor_step_uuid", "new_anchor_ref_id",
    )

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate calendar_entry_reanchor parameters beyond the base schema check:
        calendar_entry and every UUID-shaped new_anchor_* field, when supplied, must
        parse as a UUID.

        Raises:
            InvalidParamsError: If calendar_entry or any new_anchor_* UUID field is
                not a valid UUID string.
        """
        params = super().validate_params(params)
        for field in self._UUID_FIELDS:
            value = params.get(field)
            if value is not None:
                try:
                    uuid.UUID(value)
                except ValueError as exc:
                    raise InvalidParamsError(f"{field} is not a valid UUID: {value!r}") from exc
        return params

    async def execute(
        self,
        calendar_entry: str,
        changed_by: str,
        new_anchor_type: str,
        new_anchor_project_id: str | None = None,
        new_anchor_file_path: str | None = None,
        new_anchor_plan_uuid: str | None = None,
        new_anchor_revision_uuid: str | None = None,
        new_anchor_step_uuid: str | None = None,
        new_anchor_step_path: str | None = None,
        new_anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            resolved_new_anchor_project_id = uuid.UUID(new_anchor_project_id) if new_anchor_project_id is not None else None
            confirmation = confirm_anchor(
                app_config,
                requested_type=new_anchor_type,
                project_id=resolved_new_anchor_project_id,
                file_path=new_anchor_file_path,
            )
            with db_connection() as conn:
                calendar_entry_uuid = uuid.UUID(calendar_entry)
                if confirmation.confirmed:
                    new_anchor = PrimaryAnchor(
                        anchor_type=new_anchor_type,
                        project_id=resolved_new_anchor_project_id,
                        file_path=new_anchor_file_path,
                        plan_uuid=uuid.UUID(new_anchor_plan_uuid) if new_anchor_plan_uuid is not None else None,
                        revision_uuid=uuid.UUID(new_anchor_revision_uuid) if new_anchor_revision_uuid is not None else None,
                        step_uuid=uuid.UUID(new_anchor_step_uuid) if new_anchor_step_uuid is not None else None,
                        step_path=new_anchor_step_path,
                        ref_id=uuid.UUID(new_anchor_ref_id) if new_anchor_ref_id is not None else None,
                    )
                else:
                    # CA could not confirm the requested project/file anchor: never
                    # persist an unverified project/file anchor -- move the entry to
                    # unanchored instead of refusing the re-anchor (bug 5926d536 precedent).
                    new_anchor = PrimaryAnchor(anchor_type="none")
                updated = reanchor_owner_form_entity(
                    conn,
                    calendar_entry_uuid,
                    changed_by=changed_by,
                    new_anchor=new_anchor,
                    entity_type="calendar_entry",
                    get_entity=get_calendar_entry,
                    not_found_code="CALENDAR_ENTRY_NOT_FOUND",
                )
                payload = updated.to_payload()
                if confirmation.applicable:
                    payload["anchor_confirmation"] = confirmation.to_payload(new_anchor_type)
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
