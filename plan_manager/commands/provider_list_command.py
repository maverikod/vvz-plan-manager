"""Command: list a paginated page of provider records filtered by type and status (C-004, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import list_providers
from plan_manager.commands.list_projection import (
    parse_view,
    project_entities,
    view_metadata_params,
    view_schema_properties,
)


class ProviderListCommand(Command):
    name: ClassVar[str] = "provider_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of provider records (C-004) filtered by type and status."
    category: ClassVar[str] = "provider"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {"description": "Optional provider type to filter by: cloud_api or self_hosted_hardware.", "type": "string"},
                "status": {"description": "Optional activity status to filter by: active or suspended.", "type": "string"},
                "include_deleted": {"description": "Include soft-deleted providers. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "type": {"description": "Optional provider type to filter by: cloud_api or self_hosted_hardware.", "type": "string", "required": False},
            "status": {"description": "Optional activity status to filter by: active or suspended.", "type": "string", "required": False},
            "include_deleted": {"description": "Include soft-deleted providers. Defaults to false.", "type": "boolean", "required": False},
        }
        parameters.update(pagination_metadata_params())
        parameters.update(view_metadata_params())
        return_value = {
            "description": "An object with a providers key holding a page of Provider records (or, with view=summary, compact projections), plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active providers.", "command": {}},
            {"description": "List only suspended providers.", "command": {"status": "suspended"}},
        ]
        best_practices = [
            "Filter by status=suspended to find providers currently out of budget or otherwise inactive.",
            "Filter by type to separate cloud_api providers from self_hosted_hardware providers.",
            "include_deleted=true surfaces soft-deleted providers for audit review; the default false hides them.",
            "Results are ordered by created_at ascending.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary returns a compact per-row projection (uuid, name, type, status, updated_at) instead of the full Provider record (drops billing_notes and quota_notes); use provider_get for full detail.",
        ]
        return provider_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        type: str | None = None,
        status: str | None = None,
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
                providers = list_providers(conn, type=type, status=status, include_deleted=include_deleted)
                total = len(providers)
                page = providers[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "providers": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
