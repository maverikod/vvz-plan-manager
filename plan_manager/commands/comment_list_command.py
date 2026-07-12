"""Command: list runtime comments with uniform filtering and pagination (C-014, C-029, C-030)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.comment_command_metadata import comment_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
    RuntimeFilters,
)
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import list_comments

FILTER_FIELDS: list[str] = [
    "project", "file", "anchor_plan", "revision", "step", "status", "kind", "owner",
    "created_after", "created_before", "active_only",
]


def _apply_in_command_filters(records: list[RuntimeComment], filters: RuntimeFilters) -> list[RuntimeComment]:
    """Filter RuntimeComment records against the fields the sibling store's list function does not accept natively."""
    project = filters.get("project")
    file_path = filters.get("file")
    revision = filters.get("revision")
    status = filters.get("status")
    kind = filters.get("kind")
    owner = filters.get("owner")
    created_after = filters.get("created_after")
    created_before = filters.get("created_before")
    active_only = filters.get("active_only")

    result: list[RuntimeComment] = []
    for record in records:
        if project is not None and (record.anchor_project_id is None or str(record.anchor_project_id) != project):
            continue
        if file_path is not None and record.anchor_file_path != file_path:
            continue
        if revision is not None and (record.anchor_revision_uuid is None or str(record.anchor_revision_uuid) != revision):
            continue
        if kind is not None and record.kind != kind:
            continue
        if owner is not None and record.author != owner:
            continue
        if status is not None:
            comment_status = "resolved" if record.resolved is True else "unresolved"
            if comment_status != status:
                continue
        if active_only is True and record.resolved is True:
            continue
        record_created_at = datetime.fromisoformat(record.created_at)
        if created_after is not None and record_created_at <= datetime.fromisoformat(created_after):
            continue
        if created_before is not None and record_created_at >= datetime.fromisoformat(created_before):
            continue
        result.append(record)
    return result


class CommentListCommand(Command):
    name: ClassVar[str] = "comment_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List runtime comments with uniform filtering and pagination."
    category: ClassVar[str] = "comment"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
                **filter_schema_properties(FILTER_FIELDS),
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            **filter_metadata_params(FILTER_FIELDS),
            **pagination_metadata_params(),
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "comments: list of filtered, paginated RuntimeComment payloads. total: count of matching comments before pagination. limit, offset: the effective pagination applied."}},
            [{"description": "List unresolved comments for a step.", "command": {"plan": "plan_manager", "step": "5a1e9b0a-2222-4444-8888-abcdefabcdef", "status": "unresolved", "limit": 50, "offset": 0}}],
            best_practices=[
                "status='resolved' matches resolved=true; every other value, including null, counts as 'unresolved'.",
                "active_only=true is a second, independent resolved filter — combining it with status can be redundant.",
                "Only anchor_plan and step filter at the SQL layer; project, file, revision, kind, owner, and created_after/before run in-command after fetching the full anchor-matched set.",
                "total is the filtered, pre-pagination count — page by advancing offset past total, there is no cursor.",
            ],
        )

    async def execute(
        self,
        plan: str,
        project: str | None = None,
        file: str | None = None,
        anchor_plan: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        owner: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        active_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                raw_params: dict[str, Any] = {
                    "project": project, "file": file, "anchor_plan": anchor_plan, "revision": revision,
                    "step": step, "status": status, "kind": kind, "owner": owner,
                    "created_after": created_after, "created_before": created_before,
                    "active_only": active_only, "limit": limit, "offset": offset,
                }
                filters = parse_filters(raw_params, FILTER_FIELDS)
                pagination = parse_pagination(raw_params)
                anchor_plan_uuid = uuid.UUID(filters.get("anchor_plan")) if filters.get("anchor_plan") is not None else None
                anchor_step_uuid = uuid.UUID(filters.get("step")) if filters.get("step") is not None else None
                records = list_comments(conn, anchor_plan_uuid=anchor_plan_uuid, anchor_step_uuid=anchor_step_uuid)
                records = _apply_in_command_filters(records, filters)
                total = len(records)
                page = records[pagination.offset: pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "comments": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
