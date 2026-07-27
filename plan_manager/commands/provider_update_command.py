"""Command: patch the mutable fields of an existing provider record (C-004, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    perform_guarded_runtime_update,
    require_mutable_patch,
)
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import get_provider, update_provider


class ProviderUpdateCommand(Command):
    name: ClassVar[str] = "provider_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing provider record (C-004) in place."
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
                "provider_uuid": {"description": "The provider_uuid identifier of the provider record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this provider.", "type": "string"},
                "type": {"description": "New provider type: cloud_api or self_hosted_hardware.", "type": "string"},
                "rented_hardware": {"description": "New rented_hardware flag for the provider.", "type": "boolean"},
                "status": {"description": "New activity status: active or suspended.", "type": "string"},
                "billing_notes": {"description": "New free-text billing notes for the provider.", "type": "string"},
                "quota_notes": {"description": "New free-text quota notes for the provider.", "type": "string"},
            },
            "required": ["provider_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "provider_uuid": {"description": "The provider_uuid identifier of the provider record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this provider.", "type": "string", "required": True},
            "type": {"description": "New provider type: cloud_api or self_hosted_hardware.", "type": "string", "required": False},
            "rented_hardware": {"description": "New rented_hardware flag for the provider.", "type": "boolean", "required": False},
            "status": {"description": "New activity status: active or suspended.", "type": "string", "required": False},
            "billing_notes": {"description": "New free-text billing notes for the provider.", "type": "string", "required": False},
            "quota_notes": {"description": "New free-text quota notes for the provider.", "type": "string", "required": False},
        }
        return_value = {"description": "The patched Provider record.", "type": "object"}
        examples = [
            {"description": "Patch a provider's billing notes.", "command": {"provider_uuid": "c6c6c6c6-0000-0000-0000-000000000000", "changed_by": "owner", "billing_notes": "invoice #4471 paid"}},
        ]
        best_practices = [
            "Only the fields supplied are patched; omitted fields keep their current stored value.",
            "At least one mutable field beyond provider_uuid and changed_by must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "name is an immutable identity field and cannot be patched; remove and re-create the provider to change it.",
            "For a pure activity-status flip, prefer the dedicated provider_set_status command over this general patch.",
            "Re-read with provider_get after the call to confirm the patch was applied as expected.",
        ]
        return provider_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        provider_uuid: str,
        changed_by: str,
        type: str | None = None,
        rented_hardware: bool | None = None,
        status: str | None = None,
        billing_notes: str | None = None,
        quota_notes: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_guarded_runtime_update(
                raw_entity_id=provider_uuid,
                get_record=get_provider,
                update_record=update_provider,
                changed_by=changed_by,
                not_found_code="PROVIDER_NOT_FOUND",
                not_found_message=f"provider not found: {provider_uuid}",
                db_connect=db_connection,
                update_fields={
                    "type": type,
                    "rented_hardware": rented_hardware,
                    "status": status,
                    "billing_notes": billing_notes,
                    "quota_notes": quota_notes,
                },
                pre_update=lambda conn, existing, update_fields: require_mutable_patch(
                    update_fields,
                    "provider_update requires at least one mutable field to patch",
                ),
            )
        except Exception as exc:
            return map_exception(exc)
