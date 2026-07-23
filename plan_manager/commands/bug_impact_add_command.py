"""Command: create one BugImpact record for a bug (C-022, C-029)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import BASE_PARAMETERS, bug_impact_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_impact_store import create_bug_impact


class BugImpactAddCommand(Command):
    name: ClassVar[str] = "bug_impact_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create one BugImpact record describing an object affected by a bug."
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug_report this impact belongs to."},
                "target_type": {"type": "string", "description": "Type of the affected object: project, file, plan, revision, step, command, runtime_service, container_image, deployment, dependency, or documentation."},
                "impact_type": {"type": "string", "description": "How the target is affected: uses_broken_api, uses_broken_contract, needs_dependency_update, needs_version_bump, needs_pull, needs_rebuild, needs_redeploy, needs_test_rerun, needs_plan_update, needs_cascade, needs_documentation_update, runtime_regression_risk, data_migration_required, security_review_required, defect_source, or unknown. Use defect_source for the single project that owns the underlying defect of a cross-project bug; use the other values for projects that are merely affected as dependents."},
                "created_by": {"type": "string", "description": "Actor identifier recorded as the creator of this impact record."},
                "status": {"type": "string", "description": "Initial impact status: suspected, confirmed, unaffected, pending_resolution, resolved, verified, or skipped (skipped requires reason and skip_decided_by). Defaults to suspected."},
                "reason": {"type": "string", "description": "Explanation for the impact status; mandatory when status is skipped."},
                "skip_decided_by": {"type": "string", "description": "Owner decision identity for a skipped impact; mandatory together with reason when status is skipped."},
                "discovery_method": {"type": "string", "description": "How this impact was discovered, e.g. manual, reverse dependency graph."},
                "target_project_id": {"type": "string", "format": "uuid", "description": "External project UUID, when target_type is project or file."},
                "target_file_path": {"type": "string", "description": "Project-relative file path, when target_type is file."},
                "target_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID, when target_type is plan."},
                "target_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID, when target_type is revision."},
                "target_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID, when target_type is step."},
                "target_step_path": {"type": "string", "description": "Step canonical path, when target_type is step."},
                "target_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID for command/runtime_service/container_image/deployment/dependency/documentation target types."},
                "target_identifier": {"type": "string", "description": "Free-form identifier for the target when no structured id/path applies."},
            },
            "required": ["plan", "bug_id", "target_type", "impact_type", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug_id": {"description": "UUID of the bug_report this impact belongs to.", "type": "string", "required": True},
            "target_type": {"description": "Type of the affected object.", "type": "string", "required": True},
            "impact_type": {"description": "How the target is affected: uses_broken_api, uses_broken_contract, needs_dependency_update, needs_version_bump, needs_pull, needs_rebuild, needs_redeploy, needs_test_rerun, needs_plan_update, needs_cascade, needs_documentation_update, runtime_regression_risk, data_migration_required, security_review_required, defect_source, or unknown. Use defect_source for the single project that owns the underlying defect of a cross-project bug; use the other values for projects that are merely affected as dependents.", "type": "string", "required": True},
            "created_by": {"description": "Actor identifier recorded as the creator of this impact record.", "type": "string", "required": True},
            "status": {"description": "Initial impact status. Defaults to suspected.", "type": "string", "required": False},
            "reason": {"description": "Explanation for the impact status; mandatory when status is skipped.", "type": "string", "required": False},
            "skip_decided_by": {"description": "Owner decision identity for a skipped impact; mandatory with reason when status is skipped.", "type": "string", "required": False},
            "discovery_method": {"description": "How this impact was discovered.", "type": "string", "required": False},
            "target_project_id": {"description": "External project UUID.", "type": "string", "required": False},
            "target_file_path": {"description": "Project-relative file path.", "type": "string", "required": False},
            "target_plan_uuid": {"description": "Plan UUID.", "type": "string", "required": False},
            "target_revision_uuid": {"description": "Revision UUID.", "type": "string", "required": False},
            "target_step_uuid": {"description": "Step UUID.", "type": "string", "required": False},
            "target_step_path": {"description": "Step canonical path.", "type": "string", "required": False},
            "target_ref_id": {"description": "Reference UUID for command/runtime_service/container_image/deployment/dependency/documentation target types.", "type": "string", "required": False},
            "target_identifier": {"description": "Free-form identifier for the target.", "type": "string", "required": False},
        }
        return bug_impact_metadata(
            cls,
            params,
            {"success": {"description": "The persisted BugImpact payload."}},
            [{
                "description": "Record that a dependent project uses a broken API surfaced by this bug.",
                "command": {
                    "plan": "plan_manager",
                    "bug_id": "11111111-1111-1111-1111-111111111111",
                    "target_type": "project",
                    "impact_type": "uses_broken_api",
                    "created_by": "alice",
                    "target_project_id": "22222222-2222-2222-2222-222222222222",
                },
            }, {
                "description": "Record the owning project of a cross-project bug as its defect source.",
                "command": {
                    "plan": "plan_manager",
                    "bug_id": "11111111-1111-1111-1111-111111111111",
                    "target_type": "project",
                    "impact_type": "defect_source",
                    "created_by": "alice",
                    "target_project_id": "33333333-3333-3333-3333-333333333333",
                },
            }],
            best_practices=[
                "Match the target_* field to target_type (e.g. target_project_id for project or file, target_step_uuid for step).",
                "Leave status at the suspected default until the impact is independently confirmed.",
                "Supply reason and skip_decided_by together whenever status is skipped.",
                "Record discovery_method to distinguish manual entries from automated discovery.",
                "Use impact_type=defect_source for the single project that owns the underlying defect of a cross-project bug; use the other impact_type values for projects that are merely affected as dependents.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        target_type: str,
        impact_type: str,
        created_by: str,
        status: str = "suspected",
        reason: str | None = None,
        skip_decided_by: str | None = None,
        discovery_method: str | None = None,
        target_project_id: str | None = None,
        target_file_path: str | None = None,
        target_plan_uuid: str | None = None,
        target_revision_uuid: str | None = None,
        target_step_uuid: str | None = None,
        target_step_path: str | None = None,
        target_ref_id: str | None = None,
        target_identifier: str | None = None,
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
                record = create_bug_impact(
                    conn,
                    bug_uuid=bug_uuid,
                    target_type=target_type,
                    impact_type=impact_type,
                    created_by=created_by,
                    status=status,
                    reason=reason,
                    skip_decided_by=skip_decided_by,
                    discovery_method=discovery_method,
                    target_project_id=validate_uuid(target_project_id) if target_project_id is not None else None,
                    target_file_path=target_file_path,
                    target_plan_uuid=validate_uuid(target_plan_uuid) if target_plan_uuid is not None else None,
                    target_revision_uuid=validate_uuid(target_revision_uuid) if target_revision_uuid is not None else None,
                    target_step_uuid=validate_uuid(target_step_uuid) if target_step_uuid is not None else None,
                    target_step_path=target_step_path,
                    target_ref_id=validate_uuid(target_ref_id) if target_ref_id is not None else None,
                    target_identifier=target_identifier,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
