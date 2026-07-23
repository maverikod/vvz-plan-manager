"""Command: create a typed link between two TODO work items (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_todo_plan_completed
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_link_store import create_todo_link
from plan_manager.storage.todo_store import get_todo


# NOTE: create_todo_link's guards route through plan_manager.domain.runtime_integrity's
# generic ensure_no_duplicate/detect_cycle primitives, which raise typed DuplicateLinkError
# and LinkCycleError subclasses of RuntimeValidationError. plan_manager.commands.errors.
# map_exception has dedicated branches for both, checked before the generic
# RuntimeValidationError branch, so a duplicate active link surfaces DUPLICATE_LINK and a
# blocking cycle surfaces LINK_CYCLE. The remaining guards (invalid link_type,
# self-reference, missing todo) still have no dedicated exception subclass and continue to
# fall through to the generic RUNTIME_VALIDATION_ERROR domain code.
class TodoLinkAddCommand(Command):
    name: ClassVar[str] = "todo_link_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a typed link between two TODO work items."
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
                "from_todo": {"type": "string", "format": "uuid", "description": "UUID of the source TODO item."},
                "to_todo": {"type": "string", "format": "uuid", "description": "UUID of the target TODO item."},
                "link_type": {"type": "string", "description": "Link type: one of relates_to, blocks, blocked_by, duplicates, caused_by, created_from, requires, followup_for."},
                "created_by": {"type": "string", "description": "Identity of the actor creating this link."},
            },
            "required": ["from_todo", "to_todo", "link_type", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "from_todo": {"description": "UUID of the source TODO item.", "type": "string", "required": True},
            "to_todo": {"description": "UUID of the target TODO item.", "type": "string", "required": True},
            "link_type": {"description": "Link type: one of relates_to, blocks, blocked_by, duplicates, caused_by, created_from, requires, followup_for.", "type": "string", "required": True},
            "created_by": {"description": "Identity of the actor creating this link.", "type": "string", "required": True},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "The created TodoLink payload."}},
            [{"description": "Link one TODO item as blocking another.", "command": {"from_todo": "11111111-1111-1111-1111-111111111111", "to_todo": "22222222-2222-2222-2222-222222222222", "link_type": "blocks", "created_by": "agent-1"}}],
            error_cases={
                "RUNTIME_VALIDATION_ERROR": {
                    "description": "A sibling todo-link domain/store guard rejected the request for a reason with no dedicated exception subclass: invalid link_type, self-reference, or a missing todo.",
                    "message": "{details}",
                    "solution": "Read the returned message, which is passed through verbatim from the domain/store guard, and adjust from_todo, to_todo, or link_type accordingly.",
                },
                "DUPLICATE_LINK": {
                    "description": "An active link with the same (from_todo, to_todo, link_type) triple already exists.",
                    "message": "duplicate link: {details}",
                    "solution": "Call todo_link_remove on the existing link first, or skip creating a duplicate.",
                },
                "LINK_CYCLE": {
                    "description": "This blocking link (blocks or blocked_by) would introduce a cycle in the blocking-link graph.",
                    "message": "cycle detected: {details}",
                    "solution": "Inspect the existing blocking links between these TODOs and remove or redirect the conflicting edge before retrying.",
                },
            },
            best_practices=[
                "Duplicate detection is exact-match on (from_todo, to_todo, link_type) among active links — a second identical call raises DUPLICATE_LINK rather than being a no-op; unlike step_dependency_add, this is NOT idempotent.",
                "Cycle detection only runs for blocking link types (blocks, blocked_by); relates_to, duplicates, caused_by, created_from, requires, and followup_for links are never cycle-checked.",
                "blocked_by is normalized to a reversed blocks edge when building the cycle graph, so a blocks A-to-B link and a blocked_by B-to-A link are cycle-equivalent.",
                "Duplicate and blocking-cycle guard failures surface as DUPLICATE_LINK and LINK_CYCLE respectively; the remaining guards (bad link_type, self-reference, missing todo) still collapse to RUNTIME_VALIDATION_ERROR — read the message text to know which of those fired.",
                "Self-links (from_todo == to_todo) are rejected before the existence and duplicate checks even run.",
            ],
        )

    async def execute(
        self,
        from_todo: str,
        to_todo: str,
        link_type: str,
        created_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                from_todo_uuid = uuid.UUID(from_todo)
                to_todo_uuid = uuid.UUID(to_todo)
                # Each endpoint's own plan-completion lock, if it has one
                # (bug c3950b83); a missing todo is left to create_todo_link's
                # own existence guard below rather than pre-empted here.
                from_record = get_todo(conn, from_todo_uuid)
                if from_record is not None:
                    refuse_if_todo_plan_completed(conn, from_record)
                to_record = get_todo(conn, to_todo_uuid)
                if to_record is not None:
                    refuse_if_todo_plan_completed(conn, to_record)
                record = create_todo_link(
                    conn,
                    from_todo_uuid=from_todo_uuid,
                    to_todo_uuid=to_todo_uuid,
                    link_type=link_type,
                    created_by=created_by,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
