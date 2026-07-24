"""Command: create a bug fix propagation record for one impact target after a source fix (C-025, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_fix_plan_completed
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.bug_propagation_command_metadata import bug_propagation_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_derived_status_store import recompute_bug_status
from plan_manager.storage.bug_fix_propagation_store import create_bug_fix_propagation
from plan_manager.storage.bug_fix_store import get_bug_fix
from plan_manager.storage.bug_impact_store import get_bug_impact


class BugPropagationCreateCommand(Command):
    name: ClassVar[str] = "bug_propagation_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a bug fix propagation record for one impact target after a source fix."
    category: ClassVar[str] = "propagation"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier (name or UUID); OPTIONAL (bug 3eec33f2, todo a5ec9c1a). The bug "
                        "fix is always resolved directly by `bug_fix_id` (globally unique). When omitted, "
                        "the PLAN_COMPLETED guard applies only to the bug fix's parent bug's own source "
                        "plan anchor, if any. When supplied, that plan must exist and must not itself be "
                        "completed."
                    ),
                },
                "bug_fix_id": {"type": "string", "description": "UUID of the bug fix this propagation is required by."},
                "impact_id": {"type": "string", "description": "UUID of the bug impact record this propagation targets."},
                "action": {"type": "string", "description": "Required downstream action (one of the 13 PropagationAction values)."},
                "created_by": {"type": "string", "description": "Actor creating this propagation record, recorded as the audited change actor."},
                "target_type": {"type": "string", "description": "Optional free-form target type label for the propagation target."},
                "target_identifier": {"type": "string", "description": "Optional free-form identifier of the propagation target."},
                "assigned_to": {"type": "string", "description": "Optional assignee responsible for carrying out the propagation action."},
            },
            "required": ["bug_fix_id", "impact_id", "action", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": (
                    "Plan identifier (name or UUID); OPTIONAL (bug 3eec33f2, todo a5ec9c1a). The bug fix "
                    "is always resolved directly by bug_fix_id. Omit it so an unrelated plan's completion "
                    "never blocks the create; supply it only when you want that plan's own completion "
                    "checked too."
                ),
                "type": "string",
                "required": False,
            },
            "bug_fix_id": {"description": "UUID of the bug fix this propagation is required by.", "type": "string", "required": True},
            "impact_id": {"description": "UUID of the bug impact record this propagation targets.", "type": "string", "required": True},
            "action": {"description": "Required downstream action (one of the 13 PropagationAction values).", "type": "string", "required": True},
            "created_by": {"description": "Actor creating this propagation record.", "type": "string", "required": True},
            "target_type": {"description": "Optional free-form target type label.", "type": "string", "required": False},
            "target_identifier": {"description": "Optional free-form identifier of the propagation target.", "type": "string", "required": False},
            "assigned_to": {"description": "Optional assignee responsible for the propagation action.", "type": "string", "required": False},
        }
        return bug_propagation_metadata(
            cls,
            params,
            {"success": {"description": "The created bug fix propagation record payload, with every UUID field rendered as a string."}},
            [{
                "description": "Create a propagation record requiring a dependency rebuild for one impact.",
                "command": {
                    "plan": "plan_manager",
                    "bug_fix_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "impact_id": "5a1e9b0a-2222-4444-8888-abcdefabcdef",
                    "action": "rebuild_package",
                    "created_by": "agent-1",
                },
            }],
            best_practices=[
                "Create one propagation record per impact target, not one covering multiple impacts.",
                "Pick action from the 13 defined PropagationAction values, e.g. rebuild_package or redeploy.",
                "Set assigned_to at creation when the responsible owner is already known.",
                "Ensure impact_id references a bug_impact already recorded for the same bug as bug_fix_id.",
                "plan is optional: the bug fix is always resolved by bug_fix_id. Omit it so an unrelated plan's completion never blocks the create; supply it only when you want that plan's own completion checked too.",
            ],
        )

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate bug_propagation_create parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If bug_fix_id or impact_id is not a valid
                UUID string.
        """
        params = super().validate_params(params)
        bug_fix_id = params.get("bug_fix_id")
        if bug_fix_id is not None:
            try:
                uuid.UUID(bug_fix_id)
            except ValueError as exc:
                raise InvalidParamsError(f"bug_fix_id is not a valid UUID: {bug_fix_id!r}") from exc
        impact_id = params.get("impact_id")
        if impact_id is not None:
            try:
                uuid.UUID(impact_id)
            except ValueError as exc:
                raise InvalidParamsError(f"impact_id is not a valid UUID: {impact_id!r}") from exc
        return params

    async def execute(
        self,
        bug_fix_id: str,
        impact_id: str,
        action: str,
        created_by: str,
        plan: str | None = None,
        target_type: str | None = None,
        target_identifier: str | None = None,
        assigned_to: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                # Bug 3eec33f2 / todo a5ec9c1a: `plan` is optional -- the bug fix
                # is always resolved directly by `bug_fix_id` (globally unique).
                if plan is not None:
                    resolve_plan(conn, plan)
                bug_fix_uuid_val = uuid.UUID(bug_fix_id)
                impact_uuid_val = uuid.UUID(impact_id)
                fix_record = get_bug_fix(conn, bug_fix_uuid_val)
                if fix_record is None:
                    raise DomainCommandError("BUG_FIX_NOT_FOUND", f"bug fix not found: {bug_fix_id}")
                refuse_if_bug_fix_plan_completed(conn, fix_record)
                if get_bug_impact(conn, impact_uuid_val) is None:
                    raise DomainCommandError("BUG_IMPACT_NOT_FOUND", f"bug impact not found: {impact_id}")
                record = create_bug_fix_propagation(
                    conn,
                    bug_fix_uuid=bug_fix_uuid_val,
                    impact_uuid=impact_uuid_val,
                    action=action,
                    created_by=created_by,
                    target_type=target_type,
                    target_identifier=target_identifier,
                    assigned_to=assigned_to,
                )
                recompute_bug_status(conn, fix_record.bug_uuid, changed_by=created_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
