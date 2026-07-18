"""Command: move a TODO item's primary anchor to a new target, with an audit record (C-012)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.anchor_confirmation import confirm_anchor
from plan_manager.commands.errors import map_exception
from plan_manager.commands.reanchor_command_metadata import REANCHOR_BEST_PRACTICES, REANCHOR_ERROR_CASES
from plan_manager.commands.todo_command_metadata import todo_metadata
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.storage.todo_reanchor_store import reanchor_todo


class TodoReanchorCommand(Command):
    name: ClassVar[str] = "todo_reanchor"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a TODO item's primary anchor to a new target, with an audit record."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todo": {"type": "string", "format": "uuid", "description": "TODO item UUID to re-anchor."},
                "changed_by": {"type": "string", "description": "Actor performing this re-anchor move, for audit."},
                "new_anchor_type": {"type": "string", "description": "The candidate new primary anchor kind: none, project, file, plan, revision, step, execution_attempt, review_result, bug, bug_fix, or todo."},
                "new_anchor_project_id": {"type": "string", "format": "uuid", "description": "Project UUID; required when new_anchor_type is project or file."},
                "new_anchor_file_path": {"type": "string", "description": "Project-relative file path; required when new_anchor_type is file."},
                "new_anchor_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID; required when new_anchor_type is plan or step."},
                "new_anchor_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID; required when new_anchor_type is revision (optionally supplied alongside step)."},
                "new_anchor_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID; required when new_anchor_type is step."},
                "new_anchor_step_path": {"type": "string", "description": "Step path, optionally supplied alongside new_anchor_step_uuid."},
                "new_anchor_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID; required when new_anchor_type is execution_attempt, review_result, bug, bug_fix, or todo."},
            },
            "required": ["todo", "changed_by", "new_anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The re-anchored TodoItem payload."}},
            [{"description": "Move a TODO item's anchor to a step.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "new_anchor_type": "step", "new_anchor_plan_uuid": "22222222-2222-2222-2222-222222222222", "new_anchor_step_uuid": "33333333-3333-3333-3333-333333333333"}}],
            error_cases=REANCHOR_ERROR_CASES,
            best_practices=REANCHOR_BEST_PRACTICES,
        )

    async def execute(
        self,
        todo: str,
        changed_by: str,
        new_anchor_type: str,
        new_anchor_project_id: str | None = None,
        new_anchor_file_path: str | None = None,
        new_anchor_plan_uuid: str | None = None,
        new_anchor_revision_uuid: str | None = None,
        new_anchor_step_uuid: str | None = None,
        new_anchor_step_path: str | None = None,
        new_anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            resolved_new_anchor_project_id = uuid.UUID(new_anchor_project_id) if new_anchor_project_id is not None else None
            confirmation = confirm_anchor(
                app_config,
                requested_type=new_anchor_type,
                project_id=resolved_new_anchor_project_id,
                file_path=new_anchor_file_path,
            )
            with db_connection() as conn:
                todo_uuid = uuid.UUID(todo)
                if confirmation.confirmed:
                    new_anchor = PrimaryAnchor(
                        anchor_type=new_anchor_type,
                        project_id=resolved_new_anchor_project_id,
                        file_path=new_anchor_file_path,
                        plan_uuid=uuid.UUID(new_anchor_plan_uuid) if new_anchor_plan_uuid is not None else None,
                        revision_uuid=uuid.UUID(new_anchor_revision_uuid) if new_anchor_revision_uuid is not None else None,
                        step_uuid=uuid.UUID(new_anchor_step_uuid) if new_anchor_step_uuid is not None else None,
                        step_path=new_anchor_step_path,
                        ref_id=uuid.UUID(new_anchor_ref_id) if new_anchor_ref_id is not None else None,
                    )
                else:
                    # CA could not confirm the requested project/file anchor: never
                    # persist an unverified project/file anchor -- move the TODO to
                    # unanchored instead of refusing the re-anchor (bug 5926d536).
                    new_anchor = PrimaryAnchor(anchor_type="none")
                updated = reanchor_todo(conn, todo_uuid, changed_by=changed_by, new_anchor=new_anchor)
                payload = updated.to_payload()
                if confirmation.applicable:
                    payload["anchor_confirmation"] = confirmation.to_payload(new_anchor_type)
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
