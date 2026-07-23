"""Command: list a paginated page of invocable model records filtered by provider, level, and execution mode (C-005, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_store import list_models
from plan_manager.commands.list_projection import (
    parse_view,
    project_entities,
    view_metadata_params,
    view_schema_properties,
)


class ModelListCommand(Command):
    name: ClassVar[str] = "model_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of invocable model records (C-005) filtered by provider, level, and execution mode."
    category: ClassVar[str] = "model"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider_uuid": {"description": "Optional provider UUID to filter by.", "type": "string"},
                "level": {"description": "Optional exact capability level to filter by.", "type": "string"},
                "execution_mode": {"description": "Optional exact execution mode to filter by: interactive or batch.", "type": "string", "enum": ["interactive", "batch"]},
                "include_deleted": {"description": "Include soft-deleted models. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "provider_uuid": {"description": "Optional provider UUID to filter by.", "type": "string", "required": False},
            "level": {"description": "Optional exact capability level to filter by.", "type": "string", "required": False},
            "execution_mode": {"description": "Optional exact execution mode to filter by: interactive or batch.", "type": "string", "required": False},
            "include_deleted": {"description": "Include soft-deleted models. Defaults to false.", "type": "boolean", "required": False},
        }
        parameters.update(pagination_metadata_params())
        parameters.update(view_metadata_params())
        return_value = {
            "description": "An object with a models key holding a page of Model records (or, with view=summary, compact projections), plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active models.", "command": {}},
        ]
        best_practices = [
            "Filter by provider_uuid to see every model of one provider, or by level to see every equivalent-level model across providers.",
            "include_deleted=true surfaces soft-deleted models for audit review; the default false hides them.",
            "Results are ordered by created_at ascending.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary returns a compact per-row projection (uuid, name, provider_uuid, level, execution_mode, updated_at) instead of the full Model record (drops context_window, cost_class, availability); use model_get for full detail.",
        ]
        return model_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        provider_uuid: str | None = None,
        level: str | None = None,
        execution_mode: str | None = None,
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
                parsed_provider_uuid = validate_uuid(provider_uuid) if provider_uuid is not None else None
                models = list_models(
                    conn,
                    provider_uuid=parsed_provider_uuid,
                    level=level,
                    execution_mode=execution_mode,
                    include_deleted=include_deleted,
                )
                total = len(models)
                page = models[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "models": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
