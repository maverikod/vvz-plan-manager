"""Command: create a typed link between two TODO work items (C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.todo_link_store import create_todo_link


# NOTE: create_todo_link raises a single generic RuntimeValidationError for every guard
# violation (invalid link_type, self-reference, missing todo, duplicate active link, or a
# blocking cycle) — the sibling domain layer does not expose distinct exception subclasses
# per guard, so the specific guard cannot be attributed at the command level. Every such
# error flows through the generic try/except Exception -> map_exception(exc) path and is
# surfaced under the single RUNTIME_VALIDATION_ERROR domain code, whose message is passed
# through verbatim from the store. No separate per-guard error codes are declared, because
# the store cannot distinguish those cases.
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
                    "description": "A sibling todo-link domain/store guard rejected the request (invalid link_type, self-reference, missing todo, duplicate active link, or a blocking cycle). The store raises a single generic RuntimeValidationError for every such violation and exposes no per-guard subclass, so the specific cause cannot be attributed at the command level.",
                    "message": "{details}",
                    "solution": "Read the returned message, which is passed through verbatim from the domain/store guard, and adjust from_todo, to_todo, or link_type accordingly.",
                },
            },
            best_practices=[
                "Duplicate detection is exact-match on (from_todo, to_todo, link_type) among active links — a second identical call raises RUNTIME_VALIDATION_ERROR rather than being a no-op; unlike step_dependency_add, this is NOT idempotent.",
                "Cycle detection only runs for blocking link types (blocks, blocked_by); relates_to, duplicates, caused_by, created_from, requires, and followup_for links are never cycle-checked.",
                "blocked_by is normalized to a reversed blocks edge when building the cycle graph, so a blocks A-to-B link and a blocked_by B-to-A link are cycle-equivalent.",
                "All guard failures (bad link_type, self-reference, missing todo, duplicate, cycle) collapse to the single RUNTIME_VALIDATION_ERROR code — read the message text to know which guard fired.",
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
                record = create_todo_link(
                    conn,
                    from_todo_uuid=uuid.UUID(from_todo),
                    to_todo_uuid=uuid.UUID(to_todo),
                    link_type=link_type,
                    created_by=created_by,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
