"""Command: list model binding runtime-configuration records filtered by plan, scope, and role (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import list_model_bindings


class ModelBindingListCommand(Command):
    name: ClassVar[str] = "model_binding_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List model binding records (C-009) filtered by plan, scope, and role."
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
        return_value = {"description": "An object with a bindings key holding a list of ModelBinding records.", "type": "object"}
        examples = [
            {"description": "List all active role-scoped bindings.", "command": {"scope": "role"}},
        ]
        best_practices = [
            "Filter by plan to see bindings scoped to that plan plus system-wide bindings; omit plan to see every binding.",
            "Filter by scope (system, plan, level, branch, step, role) or role to narrow a large binding set.",
            "include_deleted=true surfaces soft-deleted bindings for audit review; the default false hides them.",
            "Results are ordered by created_at, not inheritance specificity; use model_binding_resolve to find the winning binding for a target.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        plan: str | None = None,
        scope: str | None = None,
        role: str | None = None,
        include_deleted: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan) if plan is not None else None
                bindings = list_model_bindings(
                    conn,
                    plan_uuid=plan_uuid,
                    scope=scope,
                    role=role,
                    include_deleted=include_deleted,
                )
                return SuccessResult(data={"bindings": [binding.to_payload() for binding in bindings]})
        except Exception as exc:
            return map_exception(exc)
