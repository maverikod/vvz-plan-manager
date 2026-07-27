"""Command: rebuild stored context blocks in one batch."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.context_block_metadata import context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import (
    get_context_block,
    rebuild_context_block,
    resolve_context_revision,
)


class BlockRebuildCommand(Command):
    name: ClassVar[str] = "block_rebuild"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Rebuild stored context blocks in batch against the current working state."
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
                "block_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Stored context block UUIDs to rebuild against the current working state.",
                },
                **pagination_schema_properties(),
            },
            "required": ["plan", "block_ids"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return context_metadata(
            cls,
            {
                "plan": {"description": "Plan identifier.", "type": "string", "required": True},
                "block_ids": {
                    "description": "Stored context block UUIDs to rebuild against the current working state.",
                    "type": "array",
                    "required": True,
                },
                **pagination_metadata_params(),
            },
            {
                "success": {
                    "description": (
                        "A paginated page of rebuilt context-block summaries only. "
                        "Each row contains source_block_id, block_id, hash, kind, "
                        "node_path, child_level, revision_uuid, cascade_uuid, "
                        "common_block_id, child_ref, and is_current. The heavy "
                        "stored blocks/content body is deliberately omitted. "
                        "The response envelope also returns total, limit, and offset."
                    )
                }
            },
            [
                {
                    "description": "Rebuild two stored context blocks and return the first summary row.",
                    "command": {
                        "plan": "plan_manager",
                        "block_ids": [
                            "00000000-0000-0000-0000-000000000001",
                            "00000000-0000-0000-0000-000000000002",
                        ],
                        "limit": 1,
                        "offset": 0,
                    },
                }
            ],
            error_cases={
                "INVALID_PAGINATION": {
                    "description": "limit or offset is out of range or not an integer.",
                    "message": "limit must be between 1 and 200, got {limit}",
                    "solution": "Retry with limit in [1, 200] and offset >= 0.",
                },
                "INVALID_CONTEXT_BLOCK_KIND": {
                    "description": "A stored context_block row has a kind other than compile, common, or specific.",
                    "message": "context block kind is not rebuildable: {kind}",
                    "solution": "Repair or remove the malformed context_block row, then retry.",
                },
            },
            extra_best_practices=[
                "Use block_list or gate findings to choose stale block_ids, then rebuild them in one batch.",
                "The response is summary-only by design; call block_get on a returned block_id only when you truly need the full body.",
            ],
        )

    async def execute(
        self,
        plan: str,
        block_ids: list[str],
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                current_revision = resolve_context_revision(conn, p)
                rebuilt_common_by_source = {}
                summaries = []
                for raw_block_id in block_ids:
                    source = get_context_block(conn, p.uuid, validate_uuid(raw_block_id))
                    rebuilt = rebuild_context_block(
                        conn,
                        p,
                        source,
                        current_revision,
                        rebuilt_common_by_source,
                    )
                    summary = rebuilt.to_summary_payload()
                    summary["source_block_id"] = str(source.block_id)
                    summary["is_current"] = (
                        rebuilt.revision_uuid == current_revision.revision_uuid
                        and rebuilt.cascade_uuid == current_revision.cascade_uuid
                    )
                    summaries.append(summary)
                total = len(summaries)
                page = summaries[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(
                    data={
                        "blocks": page,
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
