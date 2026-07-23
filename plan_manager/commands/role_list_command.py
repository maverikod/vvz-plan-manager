"""Command: list a paginated page of role records (C-003, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.role_command_metadata import role_metadata
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.role_store import list_roles
from plan_manager.commands.list_projection import (
    parse_view,
    project_entities,
    view_metadata_params,
    view_schema_properties,
)


class RoleListCommand(Command):
    name: ClassVar[str] = "role_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of role records (C-003)."
    category: ClassVar[str] = "role"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_deleted": {"description": "Include soft-deleted roles. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "include_deleted": {"description": "Include soft-deleted roles. Defaults to false.", "type": "boolean", "required": False},
        }
        parameters.update(pagination_metadata_params())
        parameters.update(view_metadata_params())
        return_value = {
            "description": "An object with a roles key holding a page of Role records (or, with view=summary, compact projections), plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active roles.", "command": {}},
        ]
        best_practices = [
            "include_deleted=true surfaces soft-deleted roles for audit review; the default false hides them.",
            "There is no name filter at the store level; role names are unique, so use role_get after locating the role_uuid, or scan the full listing.",
            "Results are ordered by created_at ascending.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary returns a compact per-row projection (uuid, name, updated_at) instead of the full Role record (drops description); use role_get for full detail.",
        ]
        return role_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view)
            with db_connection() as conn:
                pagination = parse_pagination({"limit": limit, "offset": offset})
                roles = list_roles(conn, include_deleted=include_deleted)
                total = len(roles)
                page = roles[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "roles": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
