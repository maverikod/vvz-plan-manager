"""Command: list a paginated page of the retained semantic tree snapshot history for a plan."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.commands.srt_command_metadata import BASE_PARAMETERS, srt_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.srt_snapshot_store import list_srt_snapshots
from plan_manager.commands.list_projection import (
    parse_view,
    project_entities,
    view_metadata_params,
    view_schema_properties,
)

class SrtSnapshotListCommand(Command):
    name: ClassVar[str] = "srt_snapshot_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of the retained history of semantic tree snapshots for a plan (read-only)."
    category: ClassVar[str] = "srt"
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
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {**BASE_PARAMETERS, **pagination_metadata_params(), **view_metadata_params()}
        return srt_metadata(
            cls,
            params,
            {"success": {"description": "A page of SemanticTreeSnapshot payloads (or, with view=summary, compact projections) for the plan, ordered oldest first, plus total/limit/offset."}},
            [{"description": "List snapshot history for a plan.", "command": {"plan": "plan_manager"}}],
            error_cases={
                "INVALID_PAGINATION": {
                    "description": "limit or offset is out of range or not an integer.",
                    "message": "limit must be between 1 and 200, got {limit}",
                    "solution": "Retry with limit in [1, 200] and offset >= 0.",
                },
            },
            extra_best_practices=[
                "Compare offset+limit against total to detect additional pages.",
                "view=summary returns a compact per-row projection (uuid, plan_uuid, revision_uuid, tree_hash, created_at) instead of the full record (drops tree_content, the whole semantic tree, which dominates row size); there is no srt_snapshot_get command, so full detail means re-calling this command with view=full (the default).",
            ],
        )

    async def execute(
        self,
        plan: str,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view)
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                records = list_srt_snapshots(conn, p.uuid)
                total = len(records)
                page = records[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "snapshots": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
