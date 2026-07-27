"""Command: list runtime wish items with uniform filtering and pagination."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.commands.runtime_work_command_helpers import resolve_anchor_scope
from plan_manager.commands.wish_command_metadata import wish_metadata
from plan_manager.domain.wish import WISH_KINDS, WISH_STATUSES, WishKind, WishStatus
from plan_manager.runtime.context import db_connection
from plan_manager.storage.wish_store import list_wishes_page

WISH_LIST_FILTER_FIELDS = [
    "project",
    "file",
    "anchor_plan",
    "revision",
    "step",
    "status",
    "kind",
    "priority",
    "owner",
    "assignee",
    "created_after",
    "created_before",
    "active_only",
    "unanchored_only",
]
_PARSE_FILTER_FIELDS = [name for name in WISH_LIST_FILTER_FIELDS if name != "anchor_plan"]
_FILTER_ENUMS = {"status": WISH_STATUSES, "kind": WISH_KINDS}
_ENUM_OVERRIDES = {
    "status": [item.value for item in WishStatus],
    "kind": [item.value for item in WishKind],
}


class WishListCommand(Command):
    name: ClassVar[str] = "wish_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List runtime wish items with uniform filtering and pagination."
    category: ClassVar[str] = "wish"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **filter_schema_properties(WISH_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **filter_metadata_params(WISH_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_metadata_params(),
        }
        return wish_metadata(
            cls,
            params,
            {"success": {"description": "A page of WishItem payloads plus total, limit, and offset."}},
            [{"description": "List active feature wishes for one owner.", "command": {"kind": "feature", "active_only": True, "owner": "owner", "limit": 20}}],
            best_practices=[
                "Use active_only to focus on wishes still under consideration or delivery; delivered, rejected, and cancelled wishes drop out of that view.",
                "The project filter matches both directly anchored project wishes and wishes whose anchor_plan_uuid belongs to that project via plan.project_ids.",
                "total reflects the filtered match count before pagination.",
            ],
        )

    async def execute(
        self,
        project: str | None = None,
        file: str | None = None,
        anchor_plan: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        status: str | None = None,
        kind: str | None = None,
        priority: int | None = None,
        owner: str | None = None,
        assignee: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        active_only: bool | None = None,
        unanchored_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                raw_params: dict[str, Any] = {
                    "project": project,
                    "file": file,
                    "revision": revision,
                    "step": step,
                    "status": status,
                    "kind": kind,
                    "priority": priority,
                    "owner": owner,
                    "assignee": assignee,
                    "created_after": created_after,
                    "created_before": created_before,
                    "active_only": active_only,
                    "unanchored_only": unanchored_only,
                }
                filters = parse_filters(raw_params, _PARSE_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                scope = resolve_anchor_scope(
                    conn,
                    project=filters.get("project"),
                    anchor_plan=anchor_plan,
                    revision=filters.get("revision"),
                    step=filters.get("step"),
                )
                records, total = list_wishes_page(
                    conn,
                    status=filters.get("status"),
                    kind=filters.get("kind"),
                    anchor_file_path=filters.get("file"),
                    anchor_plan_uuid=scope.anchor_plan_uuid,
                    anchor_revision_uuid=scope.revision_uuid,
                    anchor_step_uuid=scope.step_uuid,
                    priority_nice=filters.get("priority"),
                    owner=filters.get("owner"),
                    assignee=filters.get("assignee"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    active_only=bool(filters.get("active_only")),
                    unanchored_only=bool(filters.get("unanchored_only")),
                    project_id=scope.project_uuid,
                    limit=pagination.limit,
                    offset=pagination.offset,
                )
                return SuccessResult(
                    data={
                        "wishes": [record.to_payload() for record in records],
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
