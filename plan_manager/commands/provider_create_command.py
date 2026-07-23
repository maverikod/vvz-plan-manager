"""Command: create a new provider record (C-004, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import create_provider


class ProviderCreateCommand(Command):
    name: ClassVar[str] = "provider_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new provider record (C-004): the source that serves a model, carrying its type, hardware ownership, activity status, and billing notes."
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
                "name": {"description": "Provider name.", "type": "string"},
                "type": {"description": "Provider type: cloud_api or self_hosted_hardware.", "type": "string"},
                "rented_hardware": {"description": "For self-hosted hardware, distinguishes rented machines (true) from owned machines (false).", "type": "boolean"},
                "status": {"description": "Activity status: active or suspended (for example, budget exhausted).", "type": "string"},
                "created_by": {"description": "Actor creating this provider, recorded on the audit trail.", "type": "string"},
                "billing_notes": {"description": "Optional free-text billing notes.", "type": "string"},
                "quota_notes": {"description": "Optional free-text quota notes.", "type": "string"},
            },
            "required": ["name", "type", "rented_hardware", "status", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Provider name.", "type": "string", "required": True},
            "type": {"description": "Provider type: cloud_api or self_hosted_hardware.", "type": "string", "required": True},
            "rented_hardware": {"description": "For self-hosted hardware, distinguishes rented machines (true) from owned machines (false).", "type": "boolean", "required": True},
            "status": {"description": "Activity status: active or suspended (for example, budget exhausted).", "type": "string", "required": True},
            "created_by": {"description": "Actor creating this provider, recorded on the audit trail.", "type": "string", "required": True},
            "billing_notes": {"description": "Optional free-text billing notes.", "type": "string", "required": False},
            "quota_notes": {"description": "Optional free-text quota notes.", "type": "string", "required": False},
        }
        return_value = {"description": "The created Provider record.", "type": "object"}
        examples = [
            {"description": "Create a self-hosted, owned-hardware provider.", "command": {"name": "on-prem-gpu-1", "type": "self_hosted_hardware", "rented_hardware": False, "status": "active", "created_by": "owner"}},
            {"description": "Create a cloud API provider.", "command": {"name": "anthropic-api", "type": "cloud_api", "rented_hardware": False, "status": "active", "created_by": "owner"}},
        ]
        best_practices = [
            "type must be cloud_api or self_hosted_hardware; status must be active or suspended - both are validated by the store and rejected with RUNTIME_VALIDATION_ERROR otherwise.",
            "rented_hardware only distinguishes owned from rented machines for self_hosted_hardware providers; pass false for cloud_api providers.",
            "Provider is the switching axis: activating another provider while one runs out of budget is a single status change via provider_set_status, not a reconfiguration of every role.",
            "Re-read with provider_get after the call to confirm the stored record.",
        ]
        return provider_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str,
        type: str,
        rented_hardware: bool,
        status: str,
        created_by: str,
        billing_notes: str | None = None,
        quota_notes: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                provider = create_provider(
                    conn,
                    name=name,
                    type=type,
                    rented_hardware=rented_hardware,
                    status=status,
                    created_by=created_by,
                    billing_notes=billing_notes,
                    quota_notes=quota_notes,
                )
                return SuccessResult(data=provider.to_payload())
        except Exception as exc:
            return map_exception(exc)
