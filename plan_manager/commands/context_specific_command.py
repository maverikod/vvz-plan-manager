"""Command: compile and store a specific delta block."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import (
    ContextRevision,
    get_context_block,
    specific_delta,
    store_context_block,
)


class ContextSpecificCommand(Command):
    name: ClassVar[str] = "context_specific"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compile a child-specific delta over a common context block."
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
                "common_block_id": {"type": "string", "description": "UUID returned by context_common."},
                "concepts": {"type": "array", "items": {"type": "string"}, "description": "Child-specific concept ids; must be within common scope."},
            },
            "required": ["plan", "common_block_id", "concepts"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "plan": BASE_PARAMETERS["plan"],
            "common_block_id": {"description": "UUID returned by context_common.", "type": "string", "required": True},
            "concepts": {"description": "Child-specific concept ids; must be within common scope.", "type": "array", "required": True},
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "Specific delta block payload with block_id, hash, common_block_id, scope_concepts, and blocks."}},
            [{"description": "Compile a child delta after context_common.", "command": {"plan": "plan_manager", "common_block_id": "00000000-0000-0000-0000-000000000000", "concepts": ["C-001"]}}],
        )

    async def execute(
        self,
        plan: str,
        common_block_id: str,
        concepts: list[str],
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                common = get_context_block(conn, p.uuid, uuid.UUID(common_block_id))
                if common.kind != "common":
                    raise DomainCommandError(
                        "COMMON_BLOCK_NOT_FOUND",
                        "common_block_id does not reference a common block",
                        {"block_id": common_block_id, "kind": common.kind},
                    )
                scope, delta = specific_delta(conn, p.uuid, common, concepts)
                record = store_context_block(
                    conn,
                    p.uuid,
                    context_revision=ContextRevision(common.revision_uuid, common.cascade_uuid),
                    node_path=common.node_path,
                    child_level=common.child_level,
                    kind="specific",
                    scope_concepts=scope,
                    content=delta,
                    common_block_id=common.block_id,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
