"""Command: return one stored context block."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import current_working_state, get_context_block


class BlockGetCommand(Command):
    name: ClassVar[str] = "block_get"
    version: ClassVar[str] = "1.1.0"
    descr: ClassVar[str] = "Return one stored context block by UUID, its 'blocks'/'content' entries paginated (bounded default and maximum page sizes)."
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
                **pagination_schema_properties(),
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
                **pagination_metadata_params(),
            },
            {
                "success": {
                    "description": (
                        "The stored ContextBlock record's scalar fields (block_id, "
                        "plan_uuid, revision_uuid, cascade_uuid, node_path, "
                        "child_level, kind, common_block_id, scope_concepts, "
                        "content_hash, hash, created_at, is_current) unchanged, plus "
                        "'blocks'/'content' holding only the current page of the "
                        "block's entry list (deterministically ordered, unchanged "
                        "from stored order), and total/limit/offset describing that "
                        "page. A block whose entry count is within the default page "
                        "size (50) returns every entry in one call, unchanged from "
                        "before this parameter existed."
                    )
                }
            },
            [
                {"description": "Fetch a stored context block (first page, default page size).", "command": {"plan": "plan_manager", "block_id": "00000000-0000-0000-0000-000000000000"}},
                {"description": "Fetch a later page of a large context block's entries.", "command": {"plan": "plan_manager", "block_id": "00000000-0000-0000-0000-000000000000", "limit": 50, "offset": 50}},
            ],
            error_cases={
                "INVALID_PAGINATION": {
                    "description": "limit or offset is out of range or not an integer.",
                    "message": "limit must be between 1 and 200, got {limit}",
                    "solution": "Retry with limit in [1, 200] and offset >= 0.",
                },
            },
            extra_best_practices=[
                "Compare offset+limit against total to detect additional pages of the block's entries.",
                "A context block's total entry count is typically small; only common blocks compiled over a wide MRS/HRS scope grow large enough to need a second page.",
            ],
        )

    async def execute(
        self,
        plan: str,
        block_id: str,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                record = get_context_block(conn, p.uuid, validate_uuid(block_id))
                working_revision, working_cascade = current_working_state(conn, p)
                payload = record.to_payload()
                payload["is_current"] = (
                    record.revision_uuid == working_revision
                    and record.cascade_uuid == working_cascade
                )
                entries = payload["content"]
                total = len(entries)
                page = entries[pagination.offset : pagination.offset + pagination.limit]
                payload["blocks"] = list(page)
                payload["content"] = list(page)
                payload["total"] = total
                payload["limit"] = pagination.limit
                payload["offset"] = pagination.offset
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
