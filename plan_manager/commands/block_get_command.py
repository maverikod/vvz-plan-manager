"""Command: return one stored context block."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import current_working_state, get_context_block


class BlockGetCommand(Command):
    name: ClassVar[str] = "block_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return one stored context block by UUID."
    category: ClassVar[str] = "context"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
                "block_id": {"type": "string", "description": "Context block UUID."},
            },
            "required": ["plan", "block_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return context_metadata(
            cls,
            {
                "plan": {"description": "Plan identifier.", "type": "string", "required": True},
                "block_id": {"description": "Context block UUID.", "type": "string", "required": True},
            },
            {"success": {"description": "Full stored ContextBlock record."}},
            [{"description": "Fetch a stored context block.", "command": {"plan": "plan_manager", "block_id": "00000000-0000-0000-0000-000000000000"}}],
        )

    async def execute(
        self,
        plan: str,
        block_id: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                record = get_context_block(conn, p.uuid, validate_uuid(block_id))
                working_revision, working_cascade = current_working_state(conn, p)
                payload = record.to_payload()
                payload["is_current"] = (
                    record.revision_uuid == working_revision
                    and record.cascade_uuid == working_cascade
                )
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
