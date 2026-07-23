"""Command: patch the mutable description field of an existing role record (C-003, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.role_command_metadata import role_metadata
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.role_store import get_role, update_role


class RoleUpdateCommand(Command):
    name: ClassVar[str] = "role_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable description field of an existing role record (C-003) in place."
    category: ClassVar[str] = "role"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "role_uuid": {"description": "The role_uuid identifier of the role record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this role.", "type": "string"},
                "description": {"description": "New free-text description for the role.", "type": "string"},
            },
            "required": ["role_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "role_uuid": {"description": "The role_uuid identifier of the role record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this role.", "type": "string", "required": True},
            "description": {"description": "New free-text description for the role.", "type": "string", "required": False},
        }
        return_value = {"description": "The patched Role record.", "type": "object"}
        examples = [
            {"description": "Patch a role's description.", "command": {"role_uuid": "c7c7c7c7-0000-0000-0000-000000000000", "changed_by": "owner", "description": "Owns bug triage and confirmation."}},
        ]
        best_practices = [
            "description is the only mutable field; it must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "name is an immutable identity field and cannot be patched; remove and re-create the role to change it.",
            "Re-read with role_get after the call to confirm the patch was applied as expected.",
        ]
        return role_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        role_uuid: str,
        changed_by: str,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(role_uuid)
                existing = get_role(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("ROLE_NOT_FOUND", f"role not found: {role_uuid}")
                if description is None:
                    raise RuntimeValidationError("role_update requires at least one mutable field to patch")
                role = update_role(
                    conn,
                    parsed_uuid,
                    changed_by=changed_by,
                    description=description,
                )
                return SuccessResult(data=role.to_payload())
        except Exception as exc:
            return map_exception(exc)
