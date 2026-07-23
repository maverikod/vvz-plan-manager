"""Command: auto-discover the suspected impact set of a bug from the reverse project dependency graph (C-022, C-023, C-029)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import BASE_PARAMETERS, bug_impact_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_plan_completed
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_impact_store import create_bug_impact
from plan_manager.storage.bug_report_store import get_bug
from plan_manager.storage.project_dependency_store import discover_suspected_targets

_DEFAULT_DISCOVERY_METHOD = "project_dependency_reverse_graph"


class BugImpactDiscoverCommand(Command):
    name: ClassVar[str] = "bug_impact_discover"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Auto-discover the suspected impact set of a bug from the reverse project dependency graph."
    category: ClassVar[str] = "impact"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug_report the discovered impacts belong to."},
                "source_project_id": {"type": "string", "format": "uuid", "description": "External project UUID where the bug's source anchor lives; the reverse dependency graph is walked from this project."},
                "impact_type": {"type": "string", "description": "Impact type applied to every discovered BugImpact record (one of: uses_broken_api, uses_broken_contract, needs_dependency_update, needs_version_bump, needs_pull, needs_rebuild, needs_redeploy, needs_test_rerun, needs_plan_update, needs_cascade, needs_documentation_update, runtime_regression_risk, data_migration_required, security_review_required, or unknown). Never pass defect_source here: discovery only creates records for dependent projects reached via the reverse graph, never for source_project_id itself."},
                "created_by": {"type": "string", "description": "Actor identifier recorded as the creator of the discovered impact records."},
                "discovery_method": {"type": "string", "description": "How these impacts were discovered. Defaults to project_dependency_reverse_graph."},
            },
            "required": ["plan", "bug_id", "source_project_id", "impact_type", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug_id": {"description": "UUID of the bug_report the discovered impacts belong to.", "type": "string", "required": True},
            "source_project_id": {"description": "External project UUID where the bug's source anchor lives.", "type": "string", "required": True},
            "impact_type": {"description": "Impact type applied to every discovered BugImpact record (one of: uses_broken_api, uses_broken_contract, needs_dependency_update, needs_version_bump, needs_pull, needs_rebuild, needs_redeploy, needs_test_rerun, needs_plan_update, needs_cascade, needs_documentation_update, runtime_regression_risk, data_migration_required, security_review_required, or unknown). Never pass defect_source here: discovery only creates records for dependent projects reached via the reverse graph, never for source_project_id itself.", "type": "string", "required": True},
            "created_by": {"description": "Actor identifier recorded as the creator of the discovered impact records.", "type": "string", "required": True},
            "discovery_method": {"description": "How these impacts were discovered. Defaults to project_dependency_reverse_graph.", "type": "string", "required": False},
        }
        return bug_impact_metadata(
            cls,
            params,
            {"success": {"description": "The list of BugImpact payloads created for the transitively dependent projects, each with status suspected."}},
            [{
                "description": "Discover the suspected impact set of a bug confirmed in a shared base component.",
                "command": {
                    "plan": "plan_manager",
                    "bug_id": "11111111-1111-1111-1111-111111111111",
                    "source_project_id": "22222222-2222-2222-2222-222222222222",
                    "impact_type": "needs_dependency_update",
                    "created_by": "alice",
                },
            }],
            best_practices=[
                "Pass the bug's confirmed source project as source_project_id so the reverse graph starts correctly.",
                "Choose impact_type carefully: it is applied uniformly to every discovered project.",
                "Discovered impacts are always created with status suspected; confirm or dismiss them individually afterward.",
                "Override discovery_method only when the walk source differs from the standard reverse dependency graph.",
                "Never use impact_type=defect_source with this command: discover only creates suspected records for dependent projects, never for the source project itself; record the defect_source impact of the owning project directly with bug_impact_add instead.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        source_project_id: str,
        impact_type: str,
        created_by: str,
        discovery_method: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                try:
                    check_row_exists(conn, "bug_report", bug_uuid, frozenset({"bug_report"}))
                except RuntimeValidationError:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                parent_bug = get_bug(conn, bug_uuid)
                if parent_bug is not None:
                    refuse_if_bug_plan_completed(conn, parent_bug)
                source_uuid = validate_uuid(source_project_id)
                method = discovery_method if discovery_method is not None else _DEFAULT_DISCOVERY_METHOD
                discovered = discover_suspected_targets(conn, source_uuid)
                created = []
                for target_uuid in discovered:
                    record = create_bug_impact(
                        conn,
                        bug_uuid=bug_uuid,
                        target_type="project",
                        target_project_id=target_uuid,
                        impact_type=impact_type,
                        created_by=created_by,
                        status="suspected",
                        discovery_method=method,
                    )
                    created.append(record)
                return SuccessResult(data={
                    "bug_impacts": [r.to_payload() for r in created],
                    "discovered_project_count": len(created),
                })
        except Exception as exc:
            return map_exception(exc)
