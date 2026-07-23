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
    VIEW_SUMMARY,
    VIEW_VALUES,
    parse_view,
    project_entities,
)

# srt_snapshot_list does NOT use list_projection's packaged
# view_schema_properties()/view_metadata_params(): those hardcode
# default="full" and per-row list-family wording. Todo 4265fa4e mandates a
# compact-by-default response (a caller listing snapshots got ~246K tokens
# of embedded tree_content/vectors truncated mid-response), so THIS
# command's default is VIEW_SUMMARY -- a deliberate, spec-mandated deviation
# from the list family's general default=full convention. The enum
# vocabulary (VIEW_VALUES) and parse_view() validator are still reused
# unchanged; only the schema-level default/description are command-local.
_VIEW_DESCRIPTION: str = (
    "Row projection shape. 'summary' (default; todo 4265fa4e) returns only "
    "uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, "
    "embedding_model, tree_hash, created_at -- the whole semantic tree "
    "(tree_content, including every own_vector/child-vector embedding) is "
    "the field that dominates row size and is never included by default. "
    "'full' opts into the complete record, tree_content and all; there is "
    "no srt_snapshot_get command, so full detail means re-calling this "
    "command with view=full and a narrow limit. One of: " + ", ".join(VIEW_VALUES) + "."
)

_VIEW_SCHEMA_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(VIEW_VALUES),
    "default": VIEW_SUMMARY,
    "description": _VIEW_DESCRIPTION,
}

_VIEW_METADATA_PARAM: dict[str, Any] = {
    "type": "string",
    "description": _VIEW_DESCRIPTION,
    "required": False,
    "enum": list(VIEW_VALUES),
}


class SrtSnapshotListCommand(Command):
    name: ClassVar[str] = "srt_snapshot_list"
    version: ClassVar[str] = "1.1.0"
    descr: ClassVar[str] = "List a paginated page of the retained history of semantic tree snapshots for a plan, newest first (read-only)."
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
                "view": dict(_VIEW_SCHEMA_PROPERTY),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {**BASE_PARAMETERS, **pagination_metadata_params(), "view": dict(_VIEW_METADATA_PARAM)}
        return srt_metadata(
            cls,
            params,
            {"success": {"description": "A page of SemanticTreeSnapshot payloads (or, with the view=summary default, compact metadata-only projections) for the plan, ordered newest first with a stable uuid tie-breaker, plus total/limit/offset."}},
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
                "view=summary (the default) returns a compact per-row projection (uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, embedding_model, tree_hash, created_at) instead of the full record (drops tree_content, the whole semantic tree including every own_vector/child-vector embedding, which dominates row size); there is no srt_snapshot_get command, so full detail means re-calling this command with view=full and a narrow limit.",
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
            view_value = parse_view(view, default=VIEW_SUMMARY)
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
