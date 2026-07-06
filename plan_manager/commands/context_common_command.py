"""Command: compile and store a common context block for child authoring."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import common_context, resolve_context_revision, store_context_block


class ContextCommonCommand(Command):
    name: ClassVar[str] = "context_common"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compile the shared common context block for a parent node."
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
                "node": {"type": "string", "description": "Parent node path, UUID, local step id, or 'plan'."},
                "child_level": {"type": "integer", "description": "Level of children being authored: 3, 4, or 5."},
                "shared_concepts": {"type": "array", "items": {"type": "string"}, "description": "Optional shared concept scope; defaults to node concepts or all plan concepts."},
                "revision": {"type": "string", "description": "Optional current head revision UUID."},
                "cascade_uuid": {"type": "string", "description": "Optional open cascade UUID."},
            },
            "required": ["plan", "node", "child_level"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "node": {"description": "Parent node path, UUID, local step id, or 'plan'.", "type": "string", "required": True},
            "child_level": {"description": "Level of children being authored: 3, 4, or 5.", "type": "integer", "required": True},
            "shared_concepts": {"description": "Optional common scope; defaults to node concepts or all plan concepts.", "type": "array", "required": False},
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "Common block payload with common_block_id, hash, scope_concepts, and blocks."}},
            [{"description": "Compile common context for tactical authoring under G-002.", "command": {"plan": "plan_manager", "node": "G-002", "child_level": 4}}],
        )

    async def execute(
        self,
        plan: str,
        node: str,
        child_level: int,
        shared_concepts: list[str] | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                context_revision = resolve_context_revision(conn, p, revision, cascade_uuid)
                node_path, scope, content = common_context(conn, p.uuid, node, child_level, shared_concepts)
                record = store_context_block(conn, p.uuid, context_revision, node_path, child_level, "common", scope, content)
                payload = record.to_payload()
                payload["common_block_id"] = payload["block_id"]
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
