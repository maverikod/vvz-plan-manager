"""Command: retrieve a single role record by identifier (C-003, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
from plan_manager.commands.role_command_metadata import role_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.role_store import get_role


class RoleGetCommand(Command):
    name: ClassVar[str] = "role_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single role record (C-003) by its role identifier."
    category: ClassVar[str] = "role"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return get_command_schema("role_uuid", "The role_uuid identifier of the role record.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = get_command_metadata_params("role_uuid", "The role_uuid identifier of the role record.")
        return_value = {"description": "The Role record.", "type": "object"}
        examples = [
            {"description": "Fetch a role by its uuid.", "command": {"role_uuid": "c7c7c7c7-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the role_uuid returned by role_create or role_list, not a tool, toolset, provider, or model uuid.",
            "get_role returns soft-deleted records too; check the deleted_at field in the payload to know if a role is still active.",
            "Use role_list first when the exact role_uuid is unknown.",
        ]
        return role_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, role_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_get(
                raw_entity_id=role_uuid,
                get_record=get_role,
                not_found_code="ROLE_NOT_FOUND",
                not_found_message=f"role not found: {role_uuid}",
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
