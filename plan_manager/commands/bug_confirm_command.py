"""Command: transition a BugReport to status 'confirmed' (C-020)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.bug_status_transitions import guard_bug_transition
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import get_bug, set_bug_status


class BugConfirmCommand(Command):
    name: ClassVar[str] = "bug_confirm"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition a bug report to status confirmed."
    category: ClassVar[str] = "bug"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **BASE_PARAMETERS,
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to confirm."},
                "changed_by": {"type": "string", "description": "Actor performing this transition, for audit."},
            },
            "required": ["plan", "bug_id", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return bug_metadata(
            cls,
            params,
            {"type": "object", "description": "The updated BugReport payload."},
            [{"description": "Confirm a reported bug.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice"}}],
            best_practices=[
                "Call bug_confirm once triage verifies the report is a real defect.",
                "Use bug_reject instead if investigation shows it is not a real defect.",
                "Supply changed_by for the audit trail.",
            ],
        )

    async def execute(self, plan: str, bug_id: str, changed_by: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                existing = get_bug(conn, bug_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                guard_bug_transition("bug_confirm", existing.status)
                updated = set_bug_status(conn, bug_uuid, changed_by=changed_by, status="confirmed")
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
