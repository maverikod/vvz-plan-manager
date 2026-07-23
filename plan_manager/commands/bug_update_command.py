"""Command: patch mutable fields of an existing BugReport (C-020)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to update."},
                "changed_by": {"type": "string", "description": "Actor performing this update, for audit."},
                "title": {"type": "string", "description": "New title."},
                "short_description": {"type": "string", "description": "New short description."},
                "detailed_description": {"type": "string", "description": "New detailed description."},
                "expected_behavior": {"type": "string", "description": "New expected behavior text."},
                "actual_behavior": {"type": "string", "description": "New actual behavior text."},
                "reproduction": {"type": "string", "description": "New reproduction steps."},
                "evidence": {"type": "object", "description": "New structured evidence payload."},
                "environment": {"type": "string", "description": "New environment description."},
                "severity": {"type": "string", "description": "New severity (blocker, critical, major, minor, trivial)."},
                "priority_nice": {"type": "integer", "description": "New nice-scale priority value in range [-20, 19]."},
                "owner": {"type": "string", "description": "New owner identifier."},
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
            [{"description": "Update a bug's severity.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice", "severity": "critical"}}],
            best_practices=[
                "Only pass the fields you want to change; omitted fields keep their prior stored value.",
                "Use severity here, not status; bug_update never performs a lifecycle transition.",
                "Always supply changed_by for the audit trail.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        changed_by: str,
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
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                existing = get_bug(conn, bug_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
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
