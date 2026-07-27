"""Command: list a paginated page of invocation profile runtime-configuration records filtered by plan, scope, and role (C-008, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.invocation_profile_command_metadata import invocation_profile_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_list_command_helpers import perform_projected_runtime_list
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.invocation_profile_store import list_invocation_profiles
from plan_manager.commands.list_projection import (
    VIEW_SUMMARY,
    VIEW_VALUES,
)

# invocation_profile_list does NOT use list_projection's packaged
# view_schema_properties()/view_metadata_params(): those hardcode
# default="full". invocation_profile_list's rows always embed a wide set of
# tuning fields (temperature, top_p, retry_policy, rate_hint,
# response_schema, etc.). Todo ffe0b0a8 (flip every SUMMARY_FIELDS-bearing
# list command's default to summary) fixes this: the default becomes
# VIEW_SUMMARY (the same deliberate deviation bug_list and srt_snapshot_list
# already made), pointing at InvocationProfile.SUMMARY_FIELDS;
# limit/offset/total pagination is unchanged. 'view=full' still opts into
# the complete record; full detail is always one invocation_profile_get
# call away either way.
_VIEW_DESCRIPTION: str = (
    "Row projection shape. 'summary' (default; todo ffe0b0a8) returns a compact "
    "per-row projection (uuid, scope, role, plan_uuid, step_path, active, "
    "updated_at) -- the tuning fields (temperature, top_p, retry_policy, "
    "rate_hint, response_schema, etc.) are never included by default. 'full' "
    "opts into the complete InvocationProfile record; use "
    "invocation_profile_get for full detail either way. One of: "
    + ", ".join(VIEW_VALUES) + "."
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


class InvocationProfileListCommand(Command):
    name: ClassVar[str] = "invocation_profile_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of invocation profile records (C-008) filtered by plan, scope, and role."
    category: ClassVar[str] = "invocation_profile"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"description": "Optional plan UUID to filter invocation profiles by.", "type": "string"},
                "scope": {"description": "Optional BindingScope value to filter by: system, plan, level, branch, step, or role.", "type": "string"},
                "role": {"description": "Optional RuntimeRole value to filter by.", "type": "string"},
                "include_deleted": {"description": "Include soft-deleted invocation profiles. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
                "view": dict(_VIEW_SCHEMA_PROPERTY),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = dict(BASE_PARAMETERS)
        parameters["plan"] = {"description": "Optional plan UUID to filter invocation profiles by.", "type": "string", "required": False}
        parameters["scope"] = {"description": "Optional BindingScope value to filter by: system, plan, level, branch, step, or role.", "type": "string", "required": False}
        parameters["role"] = {"description": "Optional RuntimeRole value to filter by.", "type": "string", "required": False}
        parameters["include_deleted"] = {"description": "Include soft-deleted invocation profiles. Defaults to false.", "type": "boolean", "required": False}
        parameters.update(pagination_metadata_params())
        parameters["view"] = dict(_VIEW_METADATA_PARAM)
        return_value = {
            "description": "An object with a profiles key holding a page of InvocationProfile records (or, with view=summary, compact projections), plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active role-scoped invocation profiles.", "command": {"scope": "role"}},
        ]
        best_practices = [
            "Filter by plan to see profiles scoped to that plan plus system-wide profiles; omit plan to see every profile.",
            "Filter by scope (system, plan, level, branch, step, role) or role to narrow a large profile set.",
            "include_deleted=true surfaces soft-deleted profiles for audit review; the default false hides them.",
            "Results are ordered by created_at, not inheritance specificity; a future resolve command will find the winning profile for a target the same way model_binding_resolve does for bindings.",
            "Compare offset+limit against total to detect additional pages.",
            "view=summary (the default; todo ffe0b0a8) returns a compact per-row projection (uuid, scope, role, plan_uuid, step_path, active, updated_at) instead of the full InvocationProfile record (drops the tuning fields: temperature, top_p, retry_policy, rate_hint, response_schema, etc.); use invocation_profile_get for full detail. Pass view=full to opt back into the complete record.",
        ]
        return invocation_profile_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

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
            plan_uuid = validate_uuid(plan) if plan is not None else None
            return perform_projected_runtime_list(
                fetch_records=lambda conn: list_invocation_profiles(
                    conn,
                    plan_uuid=plan_uuid,
                    scope=scope,
                    role=role,
                    include_deleted=include_deleted,
                ),
                result_key="profiles",
                limit=limit,
                offset=offset,
                view=view,
                view_default=VIEW_SUMMARY,
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
