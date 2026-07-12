"""Command: list stored context blocks."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import list_context_blocks


class BlockListCommand(Command):
    name: ClassVar[str] = "block_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List stored context block records for a plan."
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
                "node": {"type": "string", "description": "Optional exact node_path filter."},
                "kind": {"type": "string", "description": "Optional kind filter: common, specific, or compile."},
                "revision": {"type": "string", "description": "Optional revision UUID filter."},
                "cascade_uuid": {"type": "string", "description": "Optional cascade UUID filter."},
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "node": {"description": "Optional exact node_path filter.", "type": "string", "required": False},
            "kind": {"description": "Optional kind filter: common, specific, or compile.", "type": "string", "required": False},
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "Ordered summaries: block_id, hash, kind, node_path, child_level, revision_uuid, cascade_uuid."}},
            [{"description": "List common context blocks for one node.", "command": {"plan": "plan_manager", "node": "G-002", "kind": "common"}}],
        )

    async def execute(
        self,
        plan: str,
        node: str | None = None,
        kind: str | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            # Validate the optional UUID filters up front so a malformed value returns a clean
            # RUNTIME_VALIDATION_ERROR instead of a raw ValueError (-32603) from the view's
            # uuid.UUID() parse. The original strings are passed on; the view parses them itself.
            if revision is not None:
                validate_uuid(revision)
            if cascade_uuid is not None:
                validate_uuid(cascade_uuid)
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                return SuccessResult(data={"blocks": list_context_blocks(conn, p.uuid, node, kind, revision, cascade_uuid)})
        except Exception as exc:
            return map_exception(exc)
