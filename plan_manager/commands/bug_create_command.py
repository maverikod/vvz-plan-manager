"""Command: create a new BugReport with its single primary source anchor (C-020, C-021)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.bug_source import BugSource
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import create_bug


class BugCreateCommand(Command):
    name: ClassVar[str] = "bug_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new bug report with its single primary source anchor."
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
                "title": {"type": "string", "description": "Short title of the bug."},
                "short_description": {"type": "string", "description": "One-line summary of the defect."},
                "detailed_description": {"type": "string", "description": "Full description of the defect."},
                "kind": {"type": "string", "description": "Bug kind (functional, wrong_output, data_loss, regression, compatibility, stale_context, planning, performance, security, infrastructure, deployment, configuration, documentation, user_experience)."},
                "severity": {"type": "string", "description": "Bug severity (blocker, critical, major, minor, trivial)."},
                "priority_nice": {"type": "integer", "description": "Nice-scale priority value in range [-20, 19]."},
                "reporter": {"type": "string", "description": "Identifier of the reporter."},
                "created_by": {"type": "string", "description": "Actor performing this creation, for audit."},
                "status": {"type": "string", "description": "Initial bug status; defaults to 'reported' if omitted."},
                "owner": {"type": "string", "description": "Identifier of the current owner, if assigned."},
                "expected_behavior": {"type": "string", "description": "What was expected to happen."},
                "actual_behavior": {"type": "string", "description": "What actually happened."},
                "reproduction": {"type": "string", "description": "Reproduction steps."},
                "evidence": {"type": "object", "description": "Structured evidence payload."},
                "environment": {"type": "string", "description": "Environment description."},
                "duplicate_of_uuid": {"type": "string", "format": "uuid", "description": "UUID of the bug this one duplicates, if any."},
                "parent_bug_uuid": {"type": "string", "format": "uuid", "description": "UUID of the parent bug, if any."},
                "source_type": {"type": "string", "description": "Primary source anchor type: project, file, plan, revision, step, command, runtime_service, execution_attempt, or unidentified."},
                "source_project_id": {"type": "string", "format": "uuid", "description": "Project UUID; required when source_type is project, file, or execution_attempt is not used here but project/file require it."},
                "source_file_path": {"type": "string", "description": "Project-relative file path; required when source_type is file."},
                "source_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID; required when source_type is plan or step."},
                "source_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID; required when source_type is revision, optional for step."},
                "source_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID; required when source_type is step."},
                "source_step_path": {"type": "string", "description": "Step path, optional context for source_type step."},
                "source_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID; required when source_type is execution_attempt."},
                "source_command": {"type": "string", "description": "Command name; required when source_type is command."},
                "source_service": {"type": "string", "description": "Runtime service name; required when source_type is runtime_service."},
            },
            "required": [
                "plan", "title", "short_description", "detailed_description", "kind",
                "severity", "priority_nice", "reporter", "created_by", "source_type",
            ],
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
            {"type": "object", "description": "The created BugReport payload."},
            [{"description": "Create a functional bug with a file source anchor.", "command": {"plan": "my-plan", "title": "Null pointer on save", "short_description": "Save crashes", "detailed_description": "Saving with an empty title crashes the service.", "kind": "functional", "severity": "major", "priority_nice": 0, "reporter": "alice", "created_by": "alice", "source_type": "file", "source_project_id": "11111111-1111-1111-1111-111111111111", "source_file_path": "src/save.py"}}],
            best_practices=[
                "Set source_type consistently with the identifier fields it requires (e.g. file needs source_project_id and source_file_path).",
                "Leave status unset to default to 'reported' unless intentionally seeding historical data.",
                "Use priority_nice in [-20, 19]; lower values are higher priority.",
                "Record reporter and created_by even when they are the same actor.",
            ],
        )

    async def execute(
        self,
        plan: str,
        title: str,
        short_description: str,
        detailed_description: str,
        kind: str,
        severity: str,
        priority_nice: int,
        reporter: str,
        created_by: str,
        source_type: str,
        status: str | None = None,
        owner: str | None = None,
        expected_behavior: str | None = None,
        actual_behavior: str | None = None,
        reproduction: str | None = None,
        evidence: dict[str, Any] | None = None,
        environment: str | None = None,
        duplicate_of_uuid: str | None = None,
        parent_bug_uuid: str | None = None,
        source_project_id: str | None = None,
        source_file_path: str | None = None,
        source_plan_uuid: str | None = None,
        source_revision_uuid: str | None = None,
        source_step_uuid: str | None = None,
        source_step_path: str | None = None,
        source_ref_id: str | None = None,
        source_command: str | None = None,
        source_service: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                source = BugSource(
                    source_type=source_type,
                    project_id=validate_uuid(source_project_id) if source_project_id is not None else None,
                    file_path=source_file_path,
                    plan_uuid=validate_uuid(source_plan_uuid) if source_plan_uuid is not None else None,
                    revision_uuid=validate_uuid(source_revision_uuid) if source_revision_uuid is not None else None,
                    step_uuid=validate_uuid(source_step_uuid) if source_step_uuid is not None else None,
                    step_path=source_step_path,
                    ref_id=validate_uuid(source_ref_id) if source_ref_id is not None else None,
                    command=source_command,
                    service=source_service,
                )
                bug = create_bug(
                    conn,
                    title=title,
                    short_description=short_description,
                    detailed_description=detailed_description,
                    kind=kind,
                    severity=severity,
                    priority_nice=priority_nice,
                    reporter=reporter,
                    created_by=created_by,
                    source=source,
                    status=status if status is not None else "reported",
                    owner=owner,
                    expected_behavior=expected_behavior,
                    actual_behavior=actual_behavior,
                    reproduction=reproduction,
                    evidence=evidence,
                    environment=environment,
                    duplicate_of_uuid=validate_uuid(duplicate_of_uuid) if duplicate_of_uuid is not None else None,
                    parent_bug_uuid=validate_uuid(parent_bug_uuid) if parent_bug_uuid is not None else None,
                )
                return SuccessResult(data=bug.to_payload())
        except Exception as exc:
            return map_exception(exc)
