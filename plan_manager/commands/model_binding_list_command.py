"""Command: list a paginated page of model binding runtime-configuration records filtered by plan, scope, and role (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import list_model_bindings
from plan_manager.commands.list_projection import (
    VIEW_SUMMARY,
    VIEW_VALUES,
    parse_view,
    project_entities,
)

# model_binding_list does NOT use list_projection's packaged
# view_schema_properties()/view_metadata_params(): those hardcode
# default="full". Todo ffe0b0a8 (flip every SUMMARY_FIELDS-bearing list
# command's default to summary) fixes this: the default becomes VIEW_SUMMARY
# (the same deliberate deviation bug_list and srt_snapshot_list already
# made), pointing at ModelBinding.SUMMARY_FIELDS; limit/offset/total
# pagination is unchanged. 'view=full' still opts into the complete record;
# full detail is always one model_binding_get call away either way.
_VIEW_DESCRIPTION: str = (
    "Row projection shape. 'summary' (default; todo ffe0b0a8) returns a compact "
    "per-row projection (uuid, scope, role, plan_uuid, provider, model, "
    "active, updated_at) -- fallback_provider/fallback_model, max_retries, "
    "timeout, and context_budget are never included by default. 'full' opts "
    "into the complete ModelBinding record; use model_binding_get for full "
    "detail either way. One of: " + ", ".join(VIEW_VALUES) + "."
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


class ModelBindingListCommand(Command):
    name: ClassVar[str] = "model_binding_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of model binding records (C-009) filtered by plan, scope, and role."
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
                "plan": {"description": "Optional plan UUID to filter bindings by.", "type": "string"},
                "scope": {"description": "Optional BindingScope value to filter by: system, plan, level, branch, step, or role.", "type": "string"},
                "role": {"description": "Optional RuntimeRole value to filter by.", "type": "string"},
                "include_deleted": {"description": "Include soft-deleted bindings. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
                "view": dict(_VIEW_SCHEMA_PROPERTY),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = dict(BASE_PARAMETERS)
        parameters["plan"] = {"description": "Optional plan UUID to filter bindings by.", "type": "string", "required": False}
        parameters["scope"] = {"description": "Optional BindingScope value to filter by: system, plan, level, branch, step, or role.", "type": "string", "required": False}
        parameters["role"] = {"description": "Optional RuntimeRole value to filter by.", "type": "string", "required": False}
        parameters["include_deleted"] = {"description": "Include soft-deleted bindings. Defaults to false.", "type": "boolean", "required": False}
        parameters.update(pagination_metadata_params())
        parameters["view"] = dict(_VIEW_METADATA_PARAM)
        return_value = {
            "description": "An object with a bindings key holding a page of ModelBinding records (or, with view=summary, compact projections), plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active role-scoped bindings.", "command": {"scope": "role"}},
        ]
        best_practices = [
            "Filter by plan to see bindings scoped to that plan plus system-wide bindings; omit plan to see every binding.",
            "Filter by scope (system, plan, level, branch, step, role) or role to narrow a large binding set.",
            "include_deleted=true surfaces soft-deleted bindings for audit review; the default false hides them.",
            "Results are ordered by created_at, not inheritance specificity; use model_binding_resolve to find the winning binding for a target.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary (the default; todo ffe0b0a8) returns a compact per-row projection (uuid, scope, role, plan_uuid, provider, model, active, updated_at) instead of the full ModelBinding record (drops fallback_provider/fallback_model, max_retries, timeout, context_budget); use model_binding_get for full detail. Pass view=full to opt back into the complete record.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        plan: str | None = None,
        scope: str | None = None,
        role: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view, default=VIEW_SUMMARY)
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan) if plan is not None else None
                pagination = parse_pagination({"limit": limit, "offset": offset})
                bindings = list_model_bindings(
                    conn,
                    plan_uuid=plan_uuid,
                    scope=scope,
                    role=role,
                    include_deleted=include_deleted,
                )
                total = len(bindings)
                page = bindings[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "bindings": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
