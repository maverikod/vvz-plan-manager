"""Command: drive a step through the lifecycle state machine."""

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.cascade.record import CascadeError, get_open_cascade
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_set_status_metadata import get_step_set_status_metadata
from plan_manager.commands.step_ref import canonical_step_paths, resolve_step_ref
from plan_manager.domain.step_ops import set_step_status
from plan_manager.domain.step_store import get_step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


ATOMIC_EXECUTION_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {("frozen", "in_progress"), ("in_progress", "done")}
)
"""The two direct-mode execution transitions of a level-5 atomic step
(bug 957c2f6a). Both are declared legal by the status model for atomic
steps, and neither edits authored content, so they are exempt from the
cascade admission regime."""


def _is_atomic_execution_transition(
    conn, plan_uuid: uuid.UUID, target, status: str, cascade_uuid: uuid.UUID | None
) -> bool:
    """Return True iff this call is a direct-mode atomic execution transition.

    Args:
        conn: Open database connection, used only to probe for an open
            cascade.
        plan_uuid: Identity of the plan the target belongs to.
        target: The resolved step being transitioned.
        status: The requested new status.
        cascade_uuid: Parsed cascade identifier, or None in direct mode.

    Returns:
        True only for a direct-mode (cascade_uuid is None) request on a
        level-5 step whose (current status, requested status) pair is one
        of ATOMIC_EXECUTION_TRANSITIONS, AND only while the plan has NO
        open cascade. Every other request -- any other level, any other
        transition out of frozen, anything supplied with a cascade_uuid,
        and anything at all while a cascade is open -- returns False and
        stays under the regime. The open-cascade probe uses the same
        `get_open_cascade` collaborator the regime itself uses, so the
        exemption narrows the regime's verdict and never widens its write
        channel: while a cascade is open it is the plan's single write
        channel, and execution transitions go through it like every other
        mutation.
    """
    if cascade_uuid is not None or target.level != 5:
        return False
    if (target.status, status) not in ATOMIC_EXECUTION_TRANSITIONS:
        return False
    return get_open_cascade(conn, plan_uuid) is None


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
            InvalidParamsError: If cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            try:
                uuid.UUID(cascade_uuid)
            except ValueError as exc:
                raise InvalidParamsError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
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
                if _is_atomic_execution_transition(
                    conn, p.uuid, target, status, parsed_cascade_uuid
                ):
                    # Bug 957c2f6a: executing a frozen atomic step is not an
                    # edit of frozen truth -- frozen->in_progress and
                    # in_progress->done change only the runtime lifecycle of a
                    # level-5 leaf and leave its authored content untouched.
                    # The admission regime admits only draft/ready_for_review
                    # targets, so it refused the very two transitions the
                    # status model declares legal here, making a frozen plan
                    # unexecutable without a cascade. For these two
                    # transitions, and only while no cascade is open, the
                    # status model (validate_transition, with is_atomic_step)
                    # is the sole judge.
                    rec = None
                else:
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
                    nodes_after = load_steps(conn, p.uuid)
                    status_updates = step_invalidation(nodes_after, target.uuid)
                    revision = cascade_write(
                        conn, p.uuid, rec, target.uuid, snapshot, status_updates, "api",
                        f"step_set_status: {transitioned.step_id}",
                        # Bug fa15d288: scope the block invalidation to the
                        # steps this write actually touches.
                        canonical_step_paths(
                            nodes_after,
                            [target.uuid] + [step_uuid for step_uuid, _ in status_updates],
                        ),
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_set_status: {transitioned.step_id}",
                        [(target.uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                        carry_forward_paths=canonical_step_paths(nodes, [target.uuid]),
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
