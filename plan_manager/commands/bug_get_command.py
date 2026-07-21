"""Command: retrieve a single BugReport by identifier (C-020)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import get_bug


class BugGetCommand(Command):
    name: ClassVar[str] = "bug_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single bug report by identifier."
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
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID), optional. When supplied, enforces plan/bug consistency: the bug's source_plan_uuid must be NULL or equal to the resolved plan, otherwise BUG_NOT_FOUND is raised. When omitted, the bug is fetched by bug_id alone.",
                },
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to retrieve."},
            },
            "required": ["bug_id"],
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
            {"type": "object", "description": "The BugReport payload."},
            [{"description": "Retrieve a bug by id.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111"}}],
            error_cases={
                "BUG_NOT_FOUND": {
                    "description": "The supplied bug_id does not resolve to an existing BugReport, OR a plan was supplied and the bug's source_plan_uuid is set and differs from the resolved plan (plan/bug consistency guard). Bugs with source_plan_uuid NULL are accepted under any supplied plan.",
                    "message": "bug not found: {bug_id}",
                    "solution": "Call bug_list to discover the bug_id; if scoping by plan, ensure the bug is anchored to that plan or has no plan anchor (or omit plan entirely).",
                },
            },
            best_practices=[
                "Call bug_list first if you don't already have the bug_id.",
                "bug_get returns a bug regardless of soft-delete status; check the deleted_at field in the payload.",
                "Use the returned status field to decide the next valid lifecycle command to call.",
                "plan is optional and, when supplied, acts only as a consistency guard: a bug whose source_plan_uuid is set to a different plan raises BUG_NOT_FOUND. Bugs with source_plan_uuid NULL are accepted under any supplied plan.",
            ],
        )

    async def execute(self, bug_id: str, plan: str | None = None, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan) if plan is not None else None
                bug_uuid = validate_uuid(bug_id)
                bug = get_bug(conn, bug_uuid)
                if bug is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                if (
                    plan_record is not None
                    and bug.source_plan_uuid is not None
                    and bug.source_plan_uuid != plan_record.uuid
                ):
                    raise DomainCommandError(
                        "BUG_NOT_FOUND",
                        f"bug not found: {bug_id} (anchored to plan {bug.source_plan_uuid}, not the resolved plan {plan_record.uuid})",
                    )
                return SuccessResult(data=bug.to_payload())
        except Exception as exc:
            return map_exception(exc)
