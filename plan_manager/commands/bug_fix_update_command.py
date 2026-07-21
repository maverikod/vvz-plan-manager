"""Command: update fields or advance the status of an existing bug fix attempt (C-024)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.bug_fix_status_transitions import guard_fix_transition
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_store import get_bug_fix, update_bug_fix


class BugFixUpdateCommand(Command):
    name: ClassVar[str] = "bug_fix_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Update fields or advance the status of an existing bug fix attempt (C-024)."
    category: ClassVar[str] = "fix"
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
                "bug_fix": {"type": "string", "format": "uuid", "description": "UUID of the BugFix (C-024) fix attempt to update."},
                "changed_by": {"type": "string", "description": "Identifier of the actor performing this update, recorded for audit purposes."},
                "status": {"type": "string", "description": "New BugFix status (C-024): one of proposed, in_progress, implemented, failed, partial, reverted, rejected, verified."},
                "implementation_notes": {"type": "string", "description": "Updated implementation notes for the fix attempt."},
                "branch": {"type": "string", "description": "Updated source-control branch containing the fix."},
                "commit_hash": {"type": "string", "description": "Updated commit hash of the fix."},
                "pull_request": {"type": "string", "description": "Updated pull request reference for the fix."},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "Updated list of changed file paths."},
                "tests": {"type": "array", "items": {"type": "string"}, "description": "Updated list of tests added or updated for the fix."},
                "reviewer": {"type": "string", "description": "Updated identifier of the reviewer for this fix attempt."},
                "summary": {"type": "string", "description": "Updated short summary of the fix attempt."},
            },
            "required": ["plan", "bug_fix", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return bug_fix_metadata(
            cls,
            params,
            {"success": {"description": "The updated BugFix (C-024) payload."}},
            [{"description": "Advance a fix attempt to implemented.", "command": {"plan": "plan_manager", "bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent", "status": "implemented"}}],
        )

    async def execute(
        self,
        plan: str,
        bug_fix: str,
        changed_by: str,
        status: str | None = None,
        implementation_notes: str | None = None,
        branch: str | None = None,
        commit_hash: str | None = None,
        pull_request: str | None = None,
        changed_files: list[str] | None = None,
        tests: list[str] | None = None,
        reviewer: str | None = None,
        summary: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                fix_uuid = uuid.UUID(bug_fix)
                existing = get_bug_fix(conn, fix_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_FIX_NOT_FOUND", f"bug fix not found: {bug_fix}")
                if status is not None:
                    guard_fix_transition(existing.status, status)
                record = update_bug_fix(
                    conn,
                    fix_uuid,
                    changed_by=changed_by,
                    status=status,
                    implementation_notes=implementation_notes,
                    branch=branch,
                    commit_hash=commit_hash,
                    pull_request=pull_request,
                    changed_files=changed_files,
                    tests=tests,
                    reviewer=reviewer,
                    summary=summary,
                )
                return SuccessResult(data={"bug_fix": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
