"""Command: patch mutable fields of an existing BugReport (C-020)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.plan_completion_guard import refuse_if_bug_plan_completed
from plan_manager.commands.text_merge import merge_text_field
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import get_bug, update_bug


class BugUpdateCommand(Command):
    name: ClassVar[str] = "bug_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch mutable fields of an existing bug report."
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
                    "description": (
                        "Plan identifier (name or UUID); OPTIONAL (bug 3eec33f2). The bug is always "
                        "resolved directly by bug_id (globally unique), so plan is not needed for lookup. "
                        "When omitted, the PLAN_COMPLETED guard applies only to the bug's own source plan "
                        "anchor, if any (a project/file/command/runtime_service/execution_attempt/"
                        "unidentified-anchored bug has none and is never blocked by an unrelated plan's "
                        "completion). When supplied, that plan must exist and must not itself be completed."
                    ),
                },
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to update."},
                "changed_by": {"type": "string", "description": "Actor performing this update, for audit."},
                "title": {"type": "string", "description": "New title."},
                "short_description": {"type": "string", "description": "New short description."},
                "detailed_description": {"type": "string", "description": "New detailed description. See `append` to preserve history instead of replacing."},
                "expected_behavior": {"type": "string", "description": "New expected behavior text. See `append` to preserve history instead of replacing."},
                "actual_behavior": {"type": "string", "description": "New actual behavior text. See `append` to preserve history instead of replacing."},
                "reproduction": {"type": "string", "description": "New reproduction steps. See `append` to preserve history instead of replacing."},
                "evidence": {"type": "object", "description": "New structured evidence payload."},
                "environment": {"type": "string", "description": "New environment description."},
                "severity": {"type": "string", "description": "New severity (blocker, critical, major, minor, trivial)."},
                "priority_nice": {"type": "integer", "description": "New nice-scale priority value in range [-20, 19]."},
                "owner": {"type": "string", "description": "New owner identifier."},
                "append": {
                    "type": "boolean",
                    "description": (
                        "History-preserving mode for detailed_description/expected_behavior/actual_behavior/"
                        "reproduction (bug 32755092). Default false: REPLACE semantics (unchanged prior "
                        "behavior) -- the supplied text overwrites the stored field. true: the supplied text "
                        "is appended to the currently stored value, separated by a blank line; appending to "
                        "an empty/null field just sets it. Use append=true whenever you want to preserve prior "
                        "notes instead of losing them."
                    ),
                },
            },
            "required": ["bug_id", "changed_by"],
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
            [
                {"description": "Update a bug's severity.", "command": {"bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice", "severity": "critical"}},
                {"description": "Append a new investigation note without losing prior ones.", "command": {"bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice", "detailed_description": "Also reproduces on 0.1.63.", "append": True}},
            ],
            best_practices=[
                "Only pass the fields you want to change; omitted fields keep their prior stored value.",
                "Use severity here, not status; bug_update never performs a lifecycle transition.",
                "Always supply changed_by for the audit trail.",
                "plan is optional: the bug is always resolved by bug_id. Omit it for a project-anchored bug so an unrelated plan's completion never blocks the update; supply it only when you want that plan's own completion checked too.",
                "Pass append=true on detailed_description/expected_behavior/actual_behavior/reproduction to preserve prior text (joined by a blank line) instead of overwriting it; the default (append=false) keeps replacing, unchanged from before.",
            ],
        )

    async def execute(
        self,
        bug_id: str,
        changed_by: str,
        plan: str | None = None,
        title: str | None = None,
        short_description: str | None = None,
        detailed_description: str | None = None,
        expected_behavior: str | None = None,
        actual_behavior: str | None = None,
        reproduction: str | None = None,
        evidence: dict[str, Any] | None = None,
        environment: str | None = None,
        severity: str | None = None,
        priority_nice: int | None = None,
        owner: str | None = None,
        append: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                # Bug 3eec33f2: `plan` is optional -- the bug is always resolved
                # directly by bug_id (globally unique). When plan IS supplied, the
                # prior behavior (resolve + PLAN_COMPLETED check on THAT plan) is
                # preserved unchanged; refuse_if_bug_plan_completed below always
                # separately checks the bug's OWN source plan anchor regardless.
                if plan is not None:
                    resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                existing = get_bug(conn, bug_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                refuse_if_bug_plan_completed(conn, existing)
                # Bug 32755092: append=True joins the incoming text onto the
                # currently stored value instead of replacing it (history-preserving
                # mode); append=False (default) keeps the prior REPLACE semantics.
                if detailed_description is not None:
                    detailed_description = merge_text_field(existing.detailed_description, detailed_description, append)
                if expected_behavior is not None:
                    expected_behavior = merge_text_field(existing.expected_behavior, expected_behavior, append)
                if actual_behavior is not None:
                    actual_behavior = merge_text_field(existing.actual_behavior, actual_behavior, append)
                if reproduction is not None:
                    reproduction = merge_text_field(existing.reproduction, reproduction, append)
                updated = update_bug(
                    conn,
                    bug_uuid,
                    changed_by=changed_by,
                    title=title,
                    short_description=short_description,
                    detailed_description=detailed_description,
                    expected_behavior=expected_behavior,
                    actual_behavior=actual_behavior,
                    reproduction=reproduction,
                    evidence=evidence,
                    environment=environment,
                    severity=severity,
                    priority_nice=priority_nice,
                    owner=owner,
                )
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
