"""Command: move a discovered project dependency edge's confidence off suspected to confirmed (C-023, C-029, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import confirm_project_dependency, get_project_dependency

class ProjectDependencyConfirmCommand(Command):
    name: ClassVar[str] = "project_dependency_confirm"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a discovered project dependency edge's confidence off suspected to confirmed."
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
                "dependency_uuid": {"type": "string", "description": "Identifier of the project_dependency edge to confirm."},
                "actor": {"type": "string", "description": "Identity performing this command, recorded as the audit actor."},
            },
            "required": ["plan", "dependency_uuid", "actor"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "dependency_uuid": {"description": "Identifier of the project_dependency edge to confirm.", "type": "string", "required": True},
            "actor": {"description": "Identity performing this command, recorded as the audit actor.", "type": "string", "required": True},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The confirmed project dependency edge payload, with confidence set to confirmed."}},
            [{
                "description": "Confirm an edge discovered by project_dependency_discover.",
                "command": {
                    "plan": "my-plan",
                    "dependency_uuid": "33333333-3333-3333-3333-333333333333",
                    "actor": "alice",
                },
            }],
            best_practices=[
                "confirm_project_dependency unconditionally sets confidence to confirmed regardless of the edge's current confidence value; it is not restricted to suspected edges.",
                "Use this command to move an edge discovered by project_dependency_discover off its permanently-suspected confidence once a human or process has verified it.",
                "Idempotent: calling confirm again on an already-confirmed dependency_uuid succeeds silently.",
                "confidence is the only field this command changes; use project_dependency_update to patch dependency_type, version_constraint, or active.",
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
                resolve_plan(conn, plan)
                dep_uuid = validate_uuid(dependency_uuid)
                existing = get_project_dependency(conn, dep_uuid)
                if existing is None:
                    raise DomainCommandError(
                        "PROJECT_DEPENDENCY_NOT_FOUND",
                        f"project dependency not found: {dependency_uuid}",
                    )
                record = confirm_project_dependency(conn, dep_uuid, changed_by=actor)
                return SuccessResult(data={"project_dependency": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
