"""Command: patch the mutable fields of an existing project dependency edge (C-023, C-029, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.domain.project_dependency import DEPENDENCY_TYPES
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import get_project_dependency, update_project_dependency

class ProjectDependencyUpdateCommand(Command):
    name: ClassVar[str] = "project_dependency_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing project dependency edge."
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
                "dependency_uuid": {"type": "string", "description": "Identifier of the project_dependency edge to patch."},
                "actor": {"type": "string", "description": "Identity performing this command, recorded as the audit actor."},
                "dependency_type": {
                    "type": "string",
                    "description": "New kind of dependency edge.",
                    "enum": sorted(DEPENDENCY_TYPES),
                },
                "version_constraint": {"type": "string", "description": "New version/constraint string for the edge."},
                "active": {"type": "boolean", "description": "New active flag for the edge."},
            },
            "required": ["plan", "dependency_uuid", "actor"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "dependency_uuid": {"description": "Identifier of the project_dependency edge to patch.", "type": "string", "required": True},
            "actor": {"description": "Identity performing this command, recorded as the audit actor.", "type": "string", "required": True},
            "dependency_type": {"description": "New kind of dependency edge (library, runtime_adapter, api_contract, protocol, generated_code, container_base, deployment_base, shared_schema, tooling, test_dependency).", "type": "string", "required": False},
            "version_constraint": {"description": "New version/constraint string for the edge.", "type": "string", "required": False},
            "active": {"description": "New active flag for the edge.", "type": "boolean", "required": False},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The patched project dependency edge payload."}},
            [{
                "description": "Deactivate an edge without deleting it.",
                "command": {
                    "plan": "my-plan",
                    "dependency_uuid": "33333333-3333-3333-3333-333333333333",
                    "actor": "alice",
                    "active": False,
                },
            }],
            best_practices=[
                "Only the fields supplied are patched; omitted fields keep their current stored value.",
                "At least one of dependency_type, version_constraint, active must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
                "confidence is not patchable here; call project_dependency_confirm to move an edge's confidence off suspected.",
                "dependent_project_id and depends_on_project_id are immutable; remove and re-add the edge to change its endpoints.",
            ],
        )

    async def execute(
        self,
        plan: str,
        dependency_uuid: str,
        actor: str,
        dependency_type: str | None = None,
        version_constraint: str | None = None,
        active: bool | None = None,
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
                if dependency_type is None and version_constraint is None and active is None:
                    raise RuntimeValidationError("project_dependency_update requires at least one mutable field to patch")
                record = update_project_dependency(
                    conn,
                    dep_uuid,
                    changed_by=actor,
                    dependency_type=dependency_type,
                    version_constraint=version_constraint,
                    active=active,
                )
                return SuccessResult(data={"project_dependency": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
