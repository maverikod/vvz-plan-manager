"""Command: create a new role record (C-003, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.role_command_metadata import role_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.role_store import create_role


class RoleCreateCommand(Command):
    name: ClassVar[str] = "role_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new role record (C-003): a first-class stored entity naming who the agent is."
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
                "name": {"description": "Unique role name (for example hrs_author, code_executor); not restricted to the 12 seeded RuntimeRole values.", "type": "string"},
                "created_by": {"description": "Actor creating this role, recorded on the audit trail.", "type": "string"},
                "description": {"description": "Optional free-text description of the role.", "type": "string"},
            },
            "required": ["name", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Unique role name (for example hrs_author, code_executor); not restricted to the 12 seeded RuntimeRole values.", "type": "string", "required": True},
            "created_by": {"description": "Actor creating this role, recorded on the audit trail.", "type": "string", "required": True},
            "description": {"description": "Optional free-text description of the role.", "type": "string", "required": False},
        }
        return_value = {"description": "The created Role record.", "type": "object"}
        examples = [
            {"description": "Create a role beyond the 12 seeded values.", "command": {"name": "release_manager", "created_by": "owner", "description": "Owns the release/deploy checklist."}},
        ]
        best_practices = [
            "Role names are unique among live rows; a duplicate live name raises RUNTIME_VALIDATION_ERROR from create_role's uniqueness pre-check.",
            "The 12 seeded RuntimeRole values (hrs_author, mrs_author, gs_author, ts_author, as_author, code_executor, owner_reviewer, conscience_reviewer, escalation_owner, bug_investigator, bug_fixer, verification_executor) are a starting convention, not a closed set; new role names are freely creatable.",
            "Re-read with role_get after the call to confirm the stored record.",
        ]
        return role_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str,
        created_by: str,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                role = create_role(
                    conn,
                    name=name,
                    created_by=created_by,
                    description=description,
                )
                return SuccessResult(data=role.to_payload())
        except Exception as exc:
            return map_exception(exc)
