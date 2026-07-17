"""Command: list runtime comments with uniform filtering and pagination (C-014, C-029, C-030)."""

from __future__ import annotations

import uuid
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
)
from plan_manager.domain.runtime_comment import COMMENT_KINDS, CommentKind
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import list_comments_page

FILTER_FIELDS: list[str] = [
    "project", "file", "anchor_plan", "revision", "step", "status", "kind", "owner",
    "created_after", "created_before", "active_only",
]

# "status" here is a synthetic resolved/unresolved derivation from the RuntimeComment.resolved
# boolean (translated to SQL in runtime_comment_store.list_comments_page), not a domain enum
# column, so it is deliberately NOT wired into the enums check here (escalated, per BUG
# 8972f59e packet: "do NOT invent one").
_FILTER_ENUMS = {"kind": COMMENT_KINDS}

# Ordered vocabularies published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error. "status" is the
# synthetic resolved/unresolved derivation (not a _FILTER_ENUMS validation
# entry, see note above), so its only two valid values are listed explicitly.
_ENUM_OVERRIDES = {
    "status": ["resolved", "unresolved"],
    "kind": [e.value for e in CommentKind],
}


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
                "plan": {"type": "string", "description": "Plan identifier (name or UUID), optional. When supplied, scopes the listing: only comments whose anchor_plan_uuid equals the resolved plan are returned; comments anchored to other plans or with no plan anchor (anchor_plan_uuid NULL) are excluded (direct anchor equality, no transitive matching). When omitted, no plan scoping is applied. The project filter (below) is independent and IS transitive via plan.project_ids."},
                **filter_schema_properties(FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": "Plan identifier (name or UUID), optional. When supplied, scopes the listing: only comments whose anchor_plan_uuid equals the resolved plan are returned; comments anchored to other plans or with no plan anchor (anchor_plan_uuid NULL) are excluded (direct anchor equality, no transitive matching). When omitted, no plan scoping is applied. The project filter (below) is independent and IS transitive via plan.project_ids.",
                "type": "string",
                "required": False,
            },
            **filter_metadata_params(FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_metadata_params(),
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "comments: list of filtered, paginated RuntimeComment payloads. total: count of matching comments before pagination. limit, offset: the effective pagination applied."}},
            [{"description": "List unresolved comments for a step.", "command": {"plan": "plan_manager", "step": "5a1e9b0a-2222-4444-8888-abcdefabcdef", "status": "unresolved", "limit": 50, "offset": 0}}],
            best_practices=[
                "The optional plan parameter scopes the listing by direct anchor: only comments with anchor_plan_uuid equal to the resolved plan are returned; NULL and foreign plan anchors are excluded (no transitive matching via anchor_ref_id or other anchor fields). Omit it to list across all plans.",
                "A supplied but nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "status='resolved' matches resolved=true; every other value, including null, counts as 'unresolved'.",
                "active_only=true is a second, independent resolved filter — combining it with status can be redundant.",
                "The plan scope, anchor_plan, step, project, file, revision, kind, owner, status, active_only, and created_after/before are all pushed down to SQL WHERE clauses -- none is applied by post-fetch, in-memory filtering. anchor_plan is redundant unless it differs from plan (which yields an empty page).",
                "The project filter matches transitively: a comment whose anchor_project_id equals the filter value matches directly, and a comment with anchor_project_id NULL still matches when its anchor_plan_uuid is bound to that project (plan.project_ids).",
                "total is the filtered, pre-pagination count — page by advancing offset past total, there is no cursor.",
            ],
        )

    async def execute(
        self,
        plan: str | None = None,
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
                plan_record = resolve_plan(conn, plan) if plan is not None else None
                raw_params: dict[str, Any] = {
                    "project": project, "file": file, "anchor_plan": anchor_plan, "revision": revision,
                    "step": step, "status": status, "kind": kind, "owner": owner,
                    "created_after": created_after, "created_before": created_before,
                    "active_only": active_only, "limit": limit, "offset": offset,
                }
                filters = parse_filters(raw_params, FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination(raw_params)
                anchor_plan_value = filters.get("anchor_plan")
                filter_anchor_plan_uuid = uuid.UUID(anchor_plan_value) if anchor_plan_value is not None else None
                step_value = filters.get("step")
                anchor_step_uuid = validate_uuid(step_value) if step_value is not None else None
                revision_value = filters.get("revision")
                anchor_revision_uuid = validate_uuid(revision_value) if revision_value is not None else None
                project_value = filters.get("project")
                project_uuid = uuid.UUID(project_value) if project_value is not None else None
                # The optional plan parameter, when supplied, scopes the query by direct anchor
                # equality (anchor_plan_uuid = resolved plan uuid; NULL and foreign anchors excluded).
                # The optional anchor_plan filter field ANDs onto that same column in SQL (see
                # list_comments_page's docstring): both must match, never widening the scope.
                records, total = list_comments_page(
                    conn,
                    anchor_plan_uuid=plan_record.uuid if plan_record is not None else None,
                    filter_anchor_plan_uuid=filter_anchor_plan_uuid,
                    anchor_step_uuid=anchor_step_uuid,
                    anchor_revision_uuid=anchor_revision_uuid,
                    anchor_file_path=filters.get("file"),
                    kind=filters.get("kind"),
                    owner=filters.get("owner"),
                    status=filters.get("status"),
                    active_only=bool(filters.get("active_only")),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    project_id=project_uuid,
                    limit=pagination.limit,
                    offset=pagination.offset,
                    include_deleted=False,
                )
                return SuccessResult(data={
                    "comments": [r.to_payload() for r in records],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
