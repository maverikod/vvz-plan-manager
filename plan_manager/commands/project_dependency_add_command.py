"""Command: create a project dependency edge between two external projects (C-023, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.commands.project_dependency_command_metadata import project_dependency_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.project_dependency_store import create_project_dependency


class ProjectDependencyAddCommand(Command):
    name: ClassVar[str] = "project_dependency_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a project dependency edge between two external projects."
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
                "dependent_project_id": {"type": "string", "description": "External analysis-server UUID of the project that depends on another (C-032)."},
                "depends_on_project_id": {"type": "string", "description": "External analysis-server UUID of the project being depended on (C-032)."},
                "dependency_type": {
                    "type": "string",
                    "description": "Kind of dependency edge.",
                    "enum": [
                        "library", "runtime_adapter", "api_contract", "protocol", "generated_code",
                        "container_base", "deployment_base", "shared_schema", "tooling", "test_dependency",
                    ],
                },
                "version_constraint": {"type": "string", "description": "Optional version/constraint string for the edge."},
                "discovery_source": {
                    "type": "string",
                    "description": "How the edge was discovered.",
                    "enum": [
                        "manual", "project_metadata", "packaging", "imports",
                        "container_manifest", "runtime_registration", "code_analysis_server",
                    ],
                },
                "confidence": {
                    "type": "string",
                    "description": "Confidence level of the edge. Defaults to unconfirmed.",
                    "enum": ["confirmed", "unconfirmed", "suspected"],
                    "default": "unconfirmed",
                },
                "active": {"type": "boolean", "description": "Whether the edge is currently active.", "default": True},
                "actor": {"type": "string", "description": "Identity performing this command, recorded as the audit actor."},
            },
            "required": [
                "plan", "dependent_project_id", "depends_on_project_id",
                "dependency_type", "discovery_source", "actor",
            ],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "dependent_project_id": {"description": "External analysis-server UUID of the project that depends on another (C-032).", "type": "string", "required": True},
            "depends_on_project_id": {"description": "External analysis-server UUID of the project being depended on (C-032).", "type": "string", "required": True},
            "dependency_type": {"description": "Kind of dependency edge (library, runtime_adapter, api_contract, protocol, generated_code, container_base, deployment_base, shared_schema, tooling, test_dependency).", "type": "string", "required": True},
            "version_constraint": {"description": "Optional version/constraint string for the edge.", "type": "string", "required": False},
            "discovery_source": {"description": "How the edge was discovered (manual, project_metadata, packaging, imports, container_manifest, runtime_registration, code_analysis_server).", "type": "string", "required": True},
            "confidence": {"description": "Confidence level of the edge (confirmed, unconfirmed, suspected); defaults to unconfirmed.", "type": "string", "required": False},
            "active": {"description": "Whether the edge is currently active; defaults to true.", "type": "boolean", "required": False},
            "actor": {"description": "Identity performing this command, recorded as the audit actor.", "type": "string", "required": True},
        }
        return project_dependency_metadata(
            cls,
            params,
            {"success": {"description": "The created project dependency edge payload."}},
            [{
                "description": "Add a manually confirmed library dependency edge.",
                "command": {
                    "plan": "my-plan",
                    "dependent_project_id": "11111111-1111-1111-1111-111111111111",
                    "depends_on_project_id": "22222222-2222-2222-2222-222222222222",
                    "dependency_type": "library",
                    "discovery_source": "manual",
                    "confidence": "confirmed",
                    "actor": "alice",
                },
            }],
            best_practices=[
                "Re-adding an identical active edge fails with DUPLICATE_ID; call project_dependency_list first to check for an existing edge.",
                "An edge that would create a cycle fails with PROJECT_DEPENDENCY_CYCLE; inspect the graph via project_dependency_list before adding.",
                "Set confidence=confirmed only when discovery_source=manual; automated discovery sources cannot be silently confirmed.",
                "dependent_project_id and depends_on_project_id must be distinct external analysis-server UUIDs, not plan_manager step or plan ids.",
            ],
        )

    async def execute(
        self,
        plan: str,
        dependent_project_id: str,
        depends_on_project_id: str,
        dependency_type: str,
        discovery_source: str,
        actor: str,
        version_constraint: str | None = None,
        confidence: str = "unconfirmed",
        active: bool = True,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                record = create_project_dependency(
                    conn,
                    dependent_project_id=validate_uuid(dependent_project_id),
                    depends_on_project_id=validate_uuid(depends_on_project_id),
                    dependency_type=dependency_type,
                    discovery_source=discovery_source,
                    created_by=actor,
                    confidence=confidence,
                    version_constraint=version_constraint,
                    active=active,
                )
                return SuccessResult(data={"project_dependency": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
