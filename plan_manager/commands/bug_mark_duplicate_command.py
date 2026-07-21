"""Command: mark a BugReport as a duplicate of another bug (C-020)."""

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
from plan_manager.storage.bug_report_store import get_bug, mark_bug_duplicate


class BugMarkDuplicateCommand(Command):
    name: ClassVar[str] = "bug_mark_duplicate"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Mark a bug report as a duplicate of another bug report."
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report being marked as a duplicate."},
                "changed_by": {"type": "string", "description": "Actor performing this transition, for audit."},
                "duplicate_of_uuid": {"type": "string", "format": "uuid", "description": "UUID of the bug report this one duplicates."},
            },
            "required": ["plan", "bug_id", "changed_by", "duplicate_of_uuid"],
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
            [{"description": "Mark a bug as a duplicate of another.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice", "duplicate_of_uuid": "22222222-2222-2222-2222-222222222222"}}],
            best_practices=[
                "duplicate_of_uuid must reference an existing bug_report row or the call fails.",
                "Use bug_mark_duplicate instead of bug_reject when the defect is already tracked under another bug.",
                "Marking a bug duplicate does not close or otherwise modify the target bug it duplicates.",
            ],
        )

    async def execute(self, plan: str, bug_id: str, changed_by: str, duplicate_of_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                existing = get_bug(conn, bug_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                guard_bug_transition("bug_mark_duplicate", existing.status)
                dup_uuid = validate_uuid(duplicate_of_uuid)
                updated = mark_bug_duplicate(conn, bug_uuid, changed_by=changed_by, duplicate_of_uuid=dup_uuid)
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
