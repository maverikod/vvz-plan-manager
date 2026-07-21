"""Command: promote an existing TODO item into a cascade request for a normative plan change (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_store import get_todo
from plan_manager.storage.cascade_request_store import create_cascade_request


class TodoPromoteToCascadeRequestCommand(Command):
    name: ClassVar[str] = "todo_promote_to_cascade_request"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Promote an existing TODO item into a cascade request for a normative plan change."
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
                "plan": {"type": "string", "description": "Plan identifier (name or UUID) the cascade request targets."},
                "todo": {"type": "string", "format": "uuid", "description": "UUID of the originating TODO item."},
                "revision": {"type": "string", "format": "uuid", "description": "Revision UUID the cascade request targets, if applicable."},
                "target_artifact": {"type": "string", "enum": ["HRS", "MRS", "GS", "TS", "AS"], "description": "The frozen-truth artifact level the discovered need targets."},
                "target_step_path": {"type": "string", "description": "Canonical step path of the targeted GS/TS/AS step, if target_artifact is GS, TS, or AS."},
                "reason": {"type": "string", "description": "Prose explaining why a normative change is discovered to be necessary."},
                "created_by": {"type": "string", "description": "Identity of the actor raising this cascade request."},
            },
            "required": ["plan", "todo", "target_artifact", "reason", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "todo": {"description": "UUID of the originating TODO item.", "type": "string", "required": True},
            "revision": {"description": "Revision UUID the cascade request targets, if applicable.", "type": "string", "required": False},
            "target_artifact": {"description": "The frozen-truth artifact level the discovered need targets: HRS, MRS, GS, TS, or AS.", "type": "string", "required": True},
            "target_step_path": {"description": "Canonical step path of the targeted GS/TS/AS step, if applicable.", "type": "string", "required": False},
            "reason": {"description": "Prose explaining why a normative change is discovered to be necessary.", "type": "string", "required": True},
            "created_by": {"description": "Identity of the actor raising this cascade request.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The created CascadeRequest payload."}},
            [{"description": "Promote a TODO item into a cascade request targeting a TS.", "command": {"plan": "plan_manager", "todo": "11111111-1111-1111-1111-111111111111", "target_artifact": "TS", "target_step_path": "G-002/T-003", "reason": "anchor validation gap found during runtime work", "created_by": "agent-1"}}],
            best_practices=[
                "target_artifact is validated only against the schema enum (HRS, MRS, GS, TS, AS); the command does not enforce that target_step_path is supplied when target_artifact is GS/TS/AS — supply it yourself whenever the target is a step-level artifact.",
                "plan accepts either a plan name or a plan UUID (resolved via resolve_plan); todo must be an existing TODO's uuid or TODO_NOT_FOUND is raised.",
                "This command only files a CascadeRequest (origin_kind fixed to todo, origin_id set to the todo's uuid) — it never mutates the frozen plan/HRS/MRS/GS/TS/AS truth itself; the cascade still goes through the plan-authoring cascade discipline.",
                "revision is optional and only meaningful when the cascade request targets a specific revision rather than the plan's current head.",
                "cascade_request has no update or delete command; it is a supersede-immutable audit-trail record of the raised need, created only by this command, and its status is not advanced by any exposed command — the actual normative change is carried out through the ordinary cascade discipline (cascade_begin, cascade_preview, cascade_commit, cascade_abort) against the target HRS/MRS/GS/TS/AS artifact, not by mutating or deleting this record.",
            ],
        )

    async def execute(
        self,
        plan: str,
        todo: str,
        target_artifact: str,
        reason: str,
        created_by: str,
        revision: str | None = None,
        target_step_path: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                todo_uuid = uuid.UUID(todo)
                existing = get_todo(conn, todo_uuid)
                if existing is None:
                    raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo}")
                revision_uuid = uuid.UUID(revision) if revision is not None else None
                record = create_cascade_request(
                    conn,
                    plan_uuid=p.uuid,
                    revision_uuid=revision_uuid,
                    target_artifact=target_artifact,
                    target_step_path=target_step_path,
                    origin_kind="todo",
                    origin_id=todo_uuid,
                    reason=reason,
                    created_by=created_by,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
