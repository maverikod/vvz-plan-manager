"""Command: retrieve a single provider record by identifier (C-004, C-015)."""

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
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import get_provider


class ProviderGetCommand(Command):
    name: ClassVar[str] = "provider_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single provider record (C-004) by its provider identifier."
    category: ClassVar[str] = "provider"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return get_command_schema("provider_uuid", "The provider_uuid identifier of the provider record.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = get_command_metadata_params("provider_uuid", "The provider_uuid identifier of the provider record.")
        return_value = {"description": "The Provider record.", "type": "object"}
        examples = [
            {"description": "Fetch a provider by its uuid.", "command": {"provider_uuid": "c6c6c6c6-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the provider_uuid returned by provider_create or provider_list, not a tool, toolset, role, or model uuid.",
            "get_provider returns soft-deleted records too; check the deleted_at field in the payload to know if a provider is still active.",
            "Use provider_list first when the exact provider_uuid is unknown.",
        ]
        return provider_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, provider_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_get(
                raw_entity_id=provider_uuid,
                get_record=get_provider,
                not_found_code="PROVIDER_NOT_FOUND",
                not_found_message=f"provider not found: {provider_uuid}",
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
