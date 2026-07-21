"""Command: transition a BugReport to status 'triaged' (C-009, C-020)."""

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

class BugTriageCommand(Command):
    name: ClassVar[str] = "bug_triage"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition a bug report to status triaged."
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to triage."},
                "changed_by": {"type": "string", "description": "Actor performing this transition, for audit."},
            },
            "required": ["plan", "bug_id", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate params against the base schema; no additional semantic checks beyond get_schema."""
        return super().validate_params(params)

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
            [{"description": "Triage a newly reported bug.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice"}}],
            best_practices=[
                "Call bug_triage to record that a reported bug has been triaged, before bug_confirm.",
                "bug_triage is legal only from status reported; the guard refuses any other current status with INVALID_RUNTIME_STATUS_TRANSITION carrying current_status and legal_targets.",
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
                guard_bug_transition("bug_triage", existing.status)
                updated = set_bug_status(conn, bug_uuid, changed_by=changed_by, status="triaged")
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
