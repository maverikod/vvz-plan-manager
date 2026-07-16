"""Command: list a paginated page of stored context blocks."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import current_working_state, list_context_blocks

class BlockListCommand(Command):
    name: ClassVar[str] = "block_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of stored context block records for a plan."
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
                **pagination_schema_properties(),
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
            **pagination_metadata_params(),
        }
        return context_metadata(
            cls,
            params,
            {"success": {"description": "A page of ordered summaries (block_id, hash, kind, node_path, child_level, revision_uuid, cascade_uuid), plus total/limit/offset."}},
            [{"description": "List common context blocks for one node.", "command": {"plan": "plan_manager", "node": "G-002", "kind": "common"}}],
            error_cases={
                "INVALID_PAGINATION": {
                    "description": "limit or offset is out of range or not an integer.",
                    "message": "limit must be between 1 and 200, got {limit}",
                    "solution": "Retry with limit in [1, 200] and offset >= 0.",
                },
            },
            extra_best_practices=[
                "Compare offset+limit against total to detect additional pages.",
            ],
        )

    async def execute(
        self,
        plan: str,
        node: str | None = None,
        kind: str | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
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
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                working_revision, working_cascade = current_working_state(conn, p)
                blocks = list_context_blocks(conn, p.uuid, node, kind, revision, cascade_uuid)
                for entry in blocks:
                    entry_revision = uuid.UUID(entry["revision_uuid"]) if entry["revision_uuid"] else None
                    entry_cascade = uuid.UUID(entry["cascade_uuid"]) if entry["cascade_uuid"] else None
                    entry["is_live"] = (
                        entry_revision == working_revision
                        and entry_cascade == working_cascade
                    )
                total = len(blocks)
                page = blocks[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "blocks": page,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
