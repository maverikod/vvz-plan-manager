"""Command: create a new fix attempt for a bug (C-024)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_derived_status_store import recompute_bug_status
from plan_manager.storage.bug_fix_store import create_bug_fix
from plan_manager.storage.bug_report_store import get_bug


class BugFixCreateCommand(Command):
    name: ClassVar[str] = "bug_fix_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new fix attempt for a bug (C-024)."
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
                "bug": {"type": "string", "format": "uuid", "description": "UUID of the BugReport (C-020) this fix attempt belongs to."},
                "fix_type": {"type": "string", "description": "BugFix fix type (C-024): one of code, configuration, migration, data, dependency_update, documentation, test, workaround, deployment, plan_cascade."},
                "summary": {"type": "string", "description": "Short summary of the fix attempt."},
                "author": {"type": "string", "description": "Identifier of the author of this fix attempt."},
                "created_by": {"type": "string", "description": "Identifier of the actor performing this create, recorded for audit purposes."},
                "status": {"type": "string", "description": "Initial BugFix status (C-024): one of proposed, in_progress, implemented, failed, partial, reverted, rejected, verified. Defaults to proposed."},
                "implementation_notes": {"type": "string", "description": "Implementation notes for the fix attempt."},
                "source_project_id": {"type": "string", "format": "uuid", "description": "External project id (C-032) where the fix is implemented."},
                "branch": {"type": "string", "description": "Source-control branch containing the fix."},
                "commit_hash": {"type": "string", "description": "Commit hash of the fix."},
                "pull_request": {"type": "string", "description": "Pull request reference for the fix."},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "List of changed file paths."},
                "tests": {"type": "array", "items": {"type": "string"}, "description": "List of tests added or updated for the fix."},
                "reviewer": {"type": "string", "description": "Identifier of the reviewer for this fix attempt."},
                "verification_method": {"type": "string", "description": "Planned verification method for this fix attempt."},
                "expected_result": {"type": "string", "description": "Expected result once the fix is verified."},
            },
            "required": ["plan", "bug", "fix_type", "summary", "author", "created_by"],
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
            {"success": {"description": "The created BugFix (C-024) payload."}},
            [{"description": "Create a fix attempt for a bug.", "command": {"plan": "plan_manager", "bug": "11111111-1111-1111-1111-111111111111", "fix_type": "code", "summary": "Patch the null check", "author": "agent", "created_by": "agent"}}],
        )

    async def execute(
        self,
        plan: str,
        bug: str,
        fix_type: str,
        summary: str,
        author: str,
        created_by: str,
        status: str = "proposed",
        implementation_notes: str | None = None,
        source_project_id: str | None = None,
        branch: str | None = None,
        commit_hash: str | None = None,
        pull_request: str | None = None,
        changed_files: list[str] | None = None,
        tests: list[str] | None = None,
        reviewer: str | None = None,
        verification_method: str | None = None,
        expected_result: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = uuid.UUID(bug)
                bug_record = get_bug(conn, bug_uuid)
                if bug_record is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug}")
                source_project_uuid = uuid.UUID(source_project_id) if source_project_id is not None else None
                record = create_bug_fix(
                    conn,
                    bug_uuid=bug_uuid,
                    fix_type=fix_type,
                    summary=summary,
                    author=author,
                    created_by=created_by,
                    status=status,
                    implementation_notes=implementation_notes,
                    source_project_id=source_project_uuid,
                    branch=branch,
                    commit_hash=commit_hash,
                    pull_request=pull_request,
                    changed_files=changed_files,
                    tests=tests,
                    reviewer=reviewer,
                    verification_method=verification_method,
                    expected_result=expected_result,
                )
                recompute_bug_status(conn, bug_uuid, changed_by=created_by)
                return SuccessResult(data={"bug_fix": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
