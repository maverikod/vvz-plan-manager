"""Command: switch a provider's activity status in a single call (C-004): the switching-axis operation."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import get_provider, set_provider_status


class ProviderSetStatusCommand(Command):
    name: ClassVar[str] = "provider_set_status"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Switch a provider's activity status in a single call (C-004): the dedicated switching-axis operation, distinct from the general provider_update."
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
                "provider_uuid": {"description": "The provider_uuid identifier of the provider record whose status is switched.", "type": "string"},
                "status": {"description": "New activity status: active or suspended.", "type": "string"},
                "changed_by": {"description": "The actor switching this provider's status, recorded on the audit trail.", "type": "string"},
            },
            "required": ["provider_uuid", "status", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "provider_uuid": {"description": "The provider_uuid identifier of the provider record whose status is switched.", "type": "string", "required": True},
            "status": {"description": "New activity status: active or suspended.", "type": "string", "required": True},
            "changed_by": {"description": "The actor switching this provider's status, recorded on the audit trail.", "type": "string", "required": True},
        }
        return_value = {"description": "The Provider record with its status switched.", "type": "object"}
        examples = [
            {"description": "Suspend a provider whose budget is exhausted.", "command": {"provider_uuid": "c6c6c6c6-0000-0000-0000-000000000000", "status": "suspended", "changed_by": "owner"}},
            {"description": "Activate a fallback provider in one call.", "command": {"provider_uuid": "d7d7d7d7-0000-0000-0000-000000000000", "status": "active", "changed_by": "owner"}},
        ]
        best_practices = [
            "This is the C-004 switching axis: activating another provider while one runs out of budget is exactly one call to this command, never a reconfiguration of every role that referenced it.",
            "status must be active or suspended; any other value fails with RUNTIME_VALIDATION_ERROR.",
            "Prefer this command over provider_update for a pure activity-status flip; provider_update remains available for patching other fields, including status alongside them.",
            "Re-read with provider_get after the call to confirm the switched status.",
        ]
        return provider_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        provider_uuid: str,
        status: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(provider_uuid)
                existing = get_provider(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("PROVIDER_NOT_FOUND", f"provider not found: {provider_uuid}")
                provider = set_provider_status(conn, parsed_uuid, status=status, changed_by=changed_by)
                return SuccessResult(data=provider.to_payload())
        except Exception as exc:
            return map_exception(exc)
