"""Command: move a bug report's primary source anchor to a new target, with an audit record (C-012)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import map_exception
from plan_manager.commands.reanchor_command_metadata import REANCHOR_BEST_PRACTICES, REANCHOR_ERROR_CASES
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.bug_source import BugSource
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_reanchor_store import reanchor_bug_source


class BugReanchorCommand(Command):
    name: ClassVar[str] = "bug_reanchor"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a bug report's primary source anchor to a new target, with an audit record."
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to re-anchor."},
                "changed_by": {"type": "string", "description": "Actor performing this re-anchor move, for audit."},
                "new_source_type": {"type": "string", "description": "The candidate new bug source kind: project, file, plan, revision, step, command, runtime_service, execution_attempt, or unidentified."},
                "new_source_project_id": {"type": "string", "format": "uuid", "description": "Project UUID; required when new_source_type is project or file."},
                "new_source_file_path": {"type": "string", "description": "Project-relative file path; required when new_source_type is file."},
                "new_source_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID; required when new_source_type is plan or step."},
                "new_source_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID; required when new_source_type is revision."},
                "new_source_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID; required when new_source_type is step."},
                "new_source_step_path": {"type": "string", "description": "Step path, optionally supplied alongside new_source_step_uuid."},
                "new_source_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID; required when new_source_type is execution_attempt."},
                "new_source_command": {"type": "string", "description": "Command name; required when new_source_type is command."},
                "new_source_service": {"type": "string", "description": "Service name; required when new_source_type is runtime_service."},
            },
            "required": ["plan", "bug_id", "changed_by", "new_source_type"],
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
            {"type": "object", "description": "The re-anchored BugReport payload."},
            [{"description": "Move a bug's source anchor to a source file.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "alice", "new_source_type": "file", "new_source_project_id": "22222222-2222-2222-2222-222222222222", "new_source_file_path": "plan_manager/domain/todo.py"}}],
            error_cases=REANCHOR_ERROR_CASES,
            best_practices=REANCHOR_BEST_PRACTICES,
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        changed_by: str,
        new_source_type: str,
        new_source_project_id: str | None = None,
        new_source_file_path: str | None = None,
        new_source_plan_uuid: str | None = None,
        new_source_revision_uuid: str | None = None,
        new_source_step_uuid: str | None = None,
        new_source_step_path: str | None = None,
        new_source_ref_id: str | None = None,
        new_source_command: str | None = None,
        new_source_service: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                new_source = BugSource(
                    source_type=new_source_type,
                    project_id=validate_uuid(new_source_project_id) if new_source_project_id is not None else None,
                    file_path=new_source_file_path,
                    plan_uuid=validate_uuid(new_source_plan_uuid) if new_source_plan_uuid is not None else None,
                    revision_uuid=validate_uuid(new_source_revision_uuid) if new_source_revision_uuid is not None else None,
                    step_uuid=validate_uuid(new_source_step_uuid) if new_source_step_uuid is not None else None,
                    step_path=new_source_step_path,
                    ref_id=validate_uuid(new_source_ref_id) if new_source_ref_id is not None else None,
                    command=new_source_command,
                    service=new_source_service,
                )
                updated = reanchor_bug_source(conn, bug_uuid, changed_by=changed_by, new_source=new_source)
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
