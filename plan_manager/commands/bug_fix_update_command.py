"""Command: update fields or advance the status of an existing bug fix attempt (C-024)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_fix_plan_completed
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.text_merge import merge_text_field
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
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier (name or UUID); OPTIONAL (bug 3eec33f2). The fix attempt is always "
                        "resolved directly by bug_fix (globally unique), so plan is not needed for lookup. "
                        "When omitted, the PLAN_COMPLETED guard applies only to the owning bug's own source "
                        "plan anchor, if any. When supplied, that plan must exist and must not itself be "
                        "completed."
                    ),
                },
                "bug_fix": {"type": "string", "format": "uuid", "description": "UUID of the BugFix (C-024) fix attempt to update."},
                "changed_by": {"type": "string", "description": "Identifier of the actor performing this update, recorded for audit purposes."},
                "status": {"type": "string", "description": "New BugFix status (C-024): one of proposed, in_progress, implemented, failed, partial, reverted, rejected, verified."},
                "implementation_notes": {"type": "string", "description": "Updated implementation notes for the fix attempt. See `append` to preserve history instead of replacing."},
                "branch": {"type": "string", "description": "Updated source-control branch containing the fix."},
                "commit_hash": {"type": "string", "description": "Updated commit hash of the fix."},
                "pull_request": {"type": "string", "description": "Updated pull request reference for the fix."},
                "changed_files": {"type": "array", "items": {"type": "string"}, "description": "Updated list of changed file paths."},
                "tests": {"type": "array", "items": {"type": "string"}, "description": "Updated list of tests added or updated for the fix."},
                "reviewer": {"type": "string", "description": "Updated identifier of the reviewer for this fix attempt."},
                "summary": {"type": "string", "description": "Updated short summary of the fix attempt."},
                "append": {
                    "type": "boolean",
                    "description": (
                        "History-preserving mode for implementation_notes (bug 32755092). Default false: "
                        "REPLACE semantics (unchanged prior behavior) -- the supplied text overwrites the "
                        "stored field. true: the supplied text is appended to the currently stored value, "
                        "separated by a blank line; appending to an empty/null field just sets it."
                    ),
                },
            },
            "required": ["bug_fix", "changed_by"],
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
            [
                {"description": "Advance a fix attempt to implemented.", "command": {"bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent", "status": "implemented"}},
                {"description": "Append a new implementation note without losing prior ones.", "command": {"bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent", "implementation_notes": "Second pass covers the edge case.", "append": True}},
            ],
            best_practices=[
                "Call bug_fix_create only after the owning bug exists.",
                "Call bug_fix_verify after implementing a fix to record whether it passed.",
                "plan is optional: the fix attempt is always resolved by bug_fix. Omit it for a project-anchored bug so an unrelated plan's completion never blocks the update; supply it only when you want that plan's own completion checked too.",
                "Pass append=true on implementation_notes to preserve prior text (joined by a blank line) instead of overwriting it; the default (append=false) keeps replacing, unchanged from before.",
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate bug_fix_update parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If bug_fix is not a valid UUID string.
        """
        params = super().validate_params(params)
        bug_fix = params.get("bug_fix")
        if bug_fix is not None:
            try:
                uuid.UUID(bug_fix)
            except ValueError as exc:
                raise InvalidParamsError(f"bug_fix is not a valid UUID: {bug_fix!r}") from exc
        return params

    async def execute(
        self,
        bug_fix: str,
        changed_by: str,
        plan: str | None = None,
        status: str | None = None,
        implementation_notes: str | None = None,
        branch: str | None = None,
        commit_hash: str | None = None,
        pull_request: str | None = None,
        changed_files: list[str] | None = None,
        tests: list[str] | None = None,
        reviewer: str | None = None,
        summary: str | None = None,
        append: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                # Bug 3eec33f2: `plan` is optional -- the fix attempt is always
                # resolved directly by bug_fix (globally unique). When plan IS
                # supplied, the prior behavior is preserved unchanged;
                # refuse_if_bug_fix_plan_completed below always separately checks
                # the owning bug's OWN source plan anchor regardless.
                if plan is not None:
                    resolve_plan(conn, plan)
                fix_uuid = uuid.UUID(bug_fix)
                existing = get_bug_fix(conn, fix_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_FIX_NOT_FOUND", f"bug fix not found: {bug_fix}")
                refuse_if_bug_fix_plan_completed(conn, existing)
                if status is not None:
                    guard_fix_transition(existing.status, status)
                # Bug 32755092: append=True joins the incoming text onto the
                # currently stored value instead of replacing it; append=False
                # (default) keeps the prior REPLACE semantics.
                if implementation_notes is not None:
                    implementation_notes = merge_text_field(existing.implementation_notes, implementation_notes, append)
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
