"""Command: drive a step through the lifecycle state machine."""

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_set_status_metadata import get_step_set_status_metadata
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.domain.step_ops import set_step_status
from plan_manager.domain.step_store import get_step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


class StepSetStatusCommand(Command):
    """Transition a step's status, refusing illegal and cascade-reserved transitions."""

    name: ClassVar[str] = "step_set_status"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition a step's status, refusing illegal and cascade-reserved transitions."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_set_status.

        Returns:
            A JSON-Schema-shaped dict with `type`, `properties`, `required`,
            and `additionalProperties` keys.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
                },
                "step_id": {
                    "type": "string",
                    "description": "Step to transition, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                },
                "status": {
                    "type": "string",
                    "description": "The new status to transition the step to.",
                    "enum": ["draft", "ready_for_review", "frozen", "needs_review", "in_progress", "done"],
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                },
            },
            "required": ["plan", "step_id", "status"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_set_status parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            ValueError: If cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(
        self,
        plan: str,
        step_id: str,
        status: str,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Transition a step's status and record the transition as a revision.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable identifier of the step to transition.
            status: The new status to transition the step to.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.

        Returns:
            SuccessResult with the transitioned step's identity, status, and
            revision_uuid on success, or ErrorResult with a stable domain
            error code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_step_ref(nodes, step_id)
                parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                try:
                    rec = check_admission(conn, p.uuid, "step", target.uuid, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    if frozen_at_or_below(nodes, target.uuid):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                set_step_status(conn, target.uuid, status)
                transitioned = get_step(conn, target.uuid)
                snapshot = step_snapshot(transitioned, status)
                if rec is not None:
                    status_updates = step_invalidation(load_steps(conn, p.uuid), target.uuid)
                    revision = cascade_write(
                        conn, p.uuid, rec, target.uuid, snapshot, status_updates, "api",
                        f"step_set_status: {transitioned.step_id}",
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_set_status: {transitioned.step_id}",
                        [(target.uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                    )
                verified = get_step(conn, target.uuid)
                data = {
                    "uuid": str(verified.uuid),
                    "step_id": verified.step_id,
                    "status": verified.status,
                    "revision_uuid": str(revision),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_set_status.

        Returns:
            The dict produced by `get_step_set_status_metadata(cls)`.
        """
        return get_step_set_status_metadata(cls)
