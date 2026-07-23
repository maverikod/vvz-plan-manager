"""Command: retrieve a single invocation profile runtime-configuration record by identifier (C-008, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.invocation_profile_command_metadata import invocation_profile_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.invocation_profile_store import get_invocation_profile


class InvocationProfileGetCommand(Command):
    name: ClassVar[str] = "invocation_profile_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single invocation profile record (C-008) by its profile identifier."
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
                "profile_uuid": {"description": "The profile_uuid identifier of the invocation_profile record.", "type": "string"},
            },
            "required": ["profile_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "profile_uuid": {"description": "The profile_uuid identifier of the invocation_profile record.", "type": "string", "required": True},
        }
        return_value = {"description": "The InvocationProfile record.", "type": "object"}
        examples = [
            {"description": "Fetch a profile by its uuid.", "command": {"profile_uuid": "b6b6b6b6-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the profile_uuid returned by invocation_profile_create or invocation_profile_list, not a plan, step, or branch uuid.",
            "get_invocation_profile returns soft-deleted records too; check the deleted_at field in the payload to know if a profile is still active.",
            "Use invocation_profile_list first when the exact profile_uuid is unknown.",
        ]
        return invocation_profile_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, profile_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(profile_uuid)
                profile = get_invocation_profile(conn, parsed_uuid)
                if profile is None:
                    raise DomainCommandError("INVOCATION_PROFILE_NOT_FOUND", f"invocation profile not found: {profile_uuid}")
                return SuccessResult(data=profile.to_payload())
        except Exception as exc:
            return map_exception(exc)
