"""Command: create a new TODO work item with a primary anchor (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.anchor_confirmation import confirm_anchor
from plan_manager.commands.errors import map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.storage.todo_store import create_todo
from plan_manager.domain.primary_anchor import PrimaryAnchor


class TodoCreateCommand(Command):
    name: ClassVar[str] = "todo_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new TODO work item with a primary anchor."
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
                "title": {"type": "string", "description": "Title of the TODO item."},
                "description": {"type": "string", "description": "Description of the TODO item."},
                "kind": {"type": "string", "description": "TODO kind (one of the TodoKind values, e.g. task, followup, cleanup, question, risk, investigation, review, update, migration, rebuild, test_rerun, documentation)."},
                "priority_nice": {"type": "integer", "description": "Nice-scale priority in [-20, 19]; lower is higher priority."},
                "created_by": {"type": "string", "description": "Identity of the actor creating this TODO item."},
                "status": {"type": "string", "description": "Initial TODO status (defaults to open)."},
                "assigned_to": {"type": "string", "description": "Identity of the actor this TODO item is assigned to."},
                "due_at": {"type": "string", "format": "date-time", "description": "ISO-8601 due timestamp."},
                "blocking_reason": {"type": "string", "description": "Reason this TODO item is currently blocked, if any."},
                "execution_result": {"type": "string", "description": "Execution result note, if any."},
                "anchor_type": {"type": "string", "description": "Primary anchor type: one of none, project, file, plan, revision, step, execution_attempt, review_result, bug, bug_fix, todo."},
                "anchor_project_id": {"type": "string", "format": "uuid", "description": "Anchor project UUID (for anchor_type=project or file)."},
                "anchor_file_path": {"type": "string", "description": "Anchor project-relative file path (for anchor_type=file)."},
                "anchor_plan_uuid": {"type": "string", "format": "uuid", "description": "Anchor plan UUID (for anchor_type=plan or step)."},
                "anchor_revision_uuid": {"type": "string", "format": "uuid", "description": "Anchor revision UUID (for anchor_type=revision or optionally step)."},
                "anchor_step_uuid": {"type": "string", "format": "uuid", "description": "Anchor step UUID (for anchor_type=step)."},
                "anchor_step_path": {"type": "string", "description": "Anchor step display path snapshot (for anchor_type=step; diagnostic only)."},
                "anchor_ref_id": {"type": "string", "format": "uuid", "description": "Anchor referenced-entity UUID (for anchor_type=execution_attempt, review_result, bug, bug_fix, or todo)."},
            },
            "required": ["title", "description", "kind", "priority_nice", "created_by", "anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "title": {"description": "Title of the TODO item.", "type": "string", "required": True},
            "description": {"description": "Description of the TODO item.", "type": "string", "required": True},
            "kind": {"description": "TODO kind (one of the TodoKind values, e.g. task, followup, cleanup, question, risk, investigation, review, update, migration, rebuild, test_rerun, documentation).", "type": "string", "required": True},
            "priority_nice": {"description": "Nice-scale priority in [-20, 19]; lower is higher priority.", "type": "integer", "required": True},
            "created_by": {"description": "Identity of the actor creating this TODO item.", "type": "string", "required": True},
            "status": {"description": "Initial TODO status (defaults to open).", "type": "string", "required": False},
            "assigned_to": {"description": "Identity of the actor this TODO item is assigned to.", "type": "string", "required": False},
            "due_at": {"description": "ISO-8601 due timestamp.", "type": "string", "required": False},
            "blocking_reason": {"description": "Reason this TODO item is currently blocked, if any.", "type": "string", "required": False},
            "execution_result": {"description": "Execution result note, if any.", "type": "string", "required": False},
            "anchor_type": {"description": "Primary anchor type: one of none, project, file, plan, revision, step, execution_attempt, review_result, bug, bug_fix, todo.", "type": "string", "required": True},
            "anchor_project_id": {"description": "Anchor project UUID (for anchor_type=project or file).", "type": "string", "required": False},
            "anchor_file_path": {"description": "Anchor project-relative file path (for anchor_type=file).", "type": "string", "required": False},
            "anchor_plan_uuid": {"description": "Anchor plan UUID (for anchor_type=plan or step).", "type": "string", "required": False},
            "anchor_revision_uuid": {"description": "Anchor revision UUID (for anchor_type=revision or optionally step).", "type": "string", "required": False},
            "anchor_step_uuid": {"description": "Anchor step UUID (for anchor_type=step).", "type": "string", "required": False},
            "anchor_step_path": {"description": "Anchor step display path snapshot (for anchor_type=step; diagnostic only).", "type": "string", "required": False},
            "anchor_ref_id": {"description": "Anchor referenced-entity UUID (for anchor_type=execution_attempt, review_result, bug, bug_fix, or todo).", "type": "string", "required": False},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The created TodoItem payload."}},
            [{
                "description": "Create a task-kind TODO anchored to a plan step.",
                "command": {
                    "title": "Fix flaky test",
                    "description": "test_foo intermittently fails under load",
                    "kind": "task",
                    "priority_nice": -5,
                    "created_by": "agent-1",
                    "anchor_type": "step",
                    "anchor_plan_uuid": "11111111-1111-1111-1111-111111111111",
                    "anchor_step_uuid": "22222222-2222-2222-2222-222222222222",
                },
            }],
            best_practices=[
                "Anchor validation is anchor_type-specific: none requires all identifier fields to be null, step requires anchor_plan_uuid and anchor_step_uuid validated against that plan/revision, file requires anchor_project_id and anchor_file_path, and todo requires anchor_ref_id to reference an existing todo_item.",
                "priority_nice follows the nice scale in [-20, 19]; lower values are higher priority, and out-of-range values are rejected before the insert.",
                "kind must be one of the fixed TodoKind vocabulary (task, followup, cleanup, question, risk, investigation, review, update, migration, rebuild, test_rerun, documentation); status defaults to open and must be a valid TodoStatus if overridden.",
                "Each call always inserts a new TODO item — there is no dedup/idempotency check, so do not blindly retry on ambiguous failures without checking whether the item was already created.",
                "anchor_type=project or file is confirmed live against the Code Analysis server before it is persisted; when CA cannot confirm the project (or file) -- unreachable/unconfigured, or a clean not-found response -- the TODO is still created but its anchor is recorded unanchored (anchor_type=none) and the response's anchor_confirmation.reason names why (ca_unreachable or not_found). Check anchor_confirmation.confirmed rather than assuming the requested anchor was honored.",
            ],
        )

    async def execute(
        self,
        title: str,
        description: str,
        kind: str,
        priority_nice: int,
        created_by: str,
        anchor_type: str,
        status: str = "open",
        assigned_to: str | None = None,
        due_at: str | None = None,
        blocking_reason: str | None = None,
        execution_result: str | None = None,
        anchor_project_id: str | None = None,
        anchor_file_path: str | None = None,
        anchor_plan_uuid: str | None = None,
        anchor_revision_uuid: str | None = None,
        anchor_step_uuid: str | None = None,
        anchor_step_path: str | None = None,
        anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            resolved_anchor_project_id = uuid.UUID(anchor_project_id) if anchor_project_id is not None else None
            confirmation = confirm_anchor(
                app_config,
                requested_type=anchor_type,
                project_id=resolved_anchor_project_id,
                file_path=anchor_file_path,
            )
            with db_connection() as conn:
                if confirmation.confirmed:
                    anchor = PrimaryAnchor(
                        anchor_type=anchor_type,
                        project_id=resolved_anchor_project_id,
                        file_path=anchor_file_path,
                        plan_uuid=uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid is not None else None,
                        revision_uuid=uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid is not None else None,
                        step_uuid=uuid.UUID(anchor_step_uuid) if anchor_step_uuid is not None else None,
                        step_path=anchor_step_path,
                        ref_id=uuid.UUID(anchor_ref_id) if anchor_ref_id is not None else None,
                    )
                else:
                    # CA could not confirm the requested project/file anchor (unreachable,
                    # unconfigured, or a clean not-found response): never persist an
                    # unverified project/file anchor -- record the TODO unanchored
                    # instead of losing the create (bug 5926d536).
                    anchor = PrimaryAnchor(anchor_type="none")
                record = create_todo(
                    conn,
                    title=title,
                    description=description,
                    kind=kind,
                    priority_nice=priority_nice,
                    created_by=created_by,
                    anchor=anchor,
                    status=status,
                    assigned_to=assigned_to,
                    due_at=due_at,
                    blocking_reason=blocking_reason,
                    execution_result=execution_result,
                )
                payload = record.to_payload()
                if confirmation.applicable:
                    payload["anchor_confirmation"] = confirmation.to_payload(anchor_type)
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
