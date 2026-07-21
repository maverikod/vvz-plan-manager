"""Command: soft-delete an existing project dependency edge (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import get_project_dependency, remove_project_dependency


class ProjectDependencyRemoveCommand(Command):
    name: ClassVar[str] = "project_dependency_remove"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Soft-delete an existing project dependency edge."
    category: ClassVar[str] = "project_dependency"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
                "dependency_uuid": {"type": "string", "description": "Identifier of the project_dependency edge to remove."},
                "actor": {"type": "string", "description": "Identity performing this command, recorded as the audit actor."},
            },
            "required": ["plan", "dependency_uuid", "actor"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "dependency_uuid": {"description": "Identifier of the project_dependency edge to remove.", "type": "string", "required": True},
            "actor": {"description": "Identity performing this command, recorded as the audit actor.", "type": "string", "required": True},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The soft-deleted project dependency edge payload."}},
            [{
                "description": "Remove an existing project dependency edge.",
                "command": {
                    "plan": "my-plan",
                    "dependency_uuid": "33333333-3333-3333-3333-333333333333",
                    "actor": "alice",
                },
            }],
            best_practices=[
                "Removal is a soft delete: the row is kept with a deleted_at timestamp, not physically deleted.",
                "Idempotent: calling remove again on an already-removed dependency_uuid succeeds silently and re-stamps deleted_at.",
                "dependency_uuid identifies the edge itself, not a project id; call project_dependency_list to find it.",
                "A removed edge stops counting in project_dependency_discover and project_dependents on the next call.",
            ],
        )

    async def execute(
        self,
        plan: str,
        dependency_uuid: str,
        actor: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                dep_uuid = validate_uuid(dependency_uuid)
                existing = get_project_dependency(conn, dep_uuid)
                if existing is None:
                    raise DomainCommandError(
                        "PROJECT_DEPENDENCY_NOT_FOUND",
                        f"project dependency not found: {dependency_uuid}",
                    )
                record = remove_project_dependency(conn, dep_uuid, changed_by=actor)
                return SuccessResult(data={"project_dependency": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
