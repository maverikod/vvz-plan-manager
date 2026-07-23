"""Command: move a step to a new parent, rewriting every reference."""

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_ancestor, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_move_metadata import get_step_move_metadata
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.domain.step_ops import move_step
from plan_manager.domain.step_store import get_step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import load_steps


class StepMoveCommand(Command):
    """Move a step to a new parent and rewrite every reference to it."""

    name: ClassVar[str] = "step_move"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a step to a new parent, rewriting every reference to it in one operation."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_move.

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
                    "description": "Step to move, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                },
                "new_parent_step_id": {
                    "type": "string",
                    "description": "New parent step, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_PARENT_STEP_ID.",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                },
            },
            "required": ["plan", "step_id", "new_parent_step_id"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_move parameters beyond the base schema check.

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
        new_parent_step_id: str,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Move a step to a new parent and record the move as a revision.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable identifier of the step to move.
            new_parent_step_id: Human-readable step_id of the new parent.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.

        Returns:
            SuccessResult with the moved step's uuid, old_step_id,
            new_step_id, new parent_step_uuid, path, status, and
            revision_uuid on success, or ErrorResult with a stable domain
            error code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_step_ref(nodes, step_id)
                new_parent = resolve_step_ref(
                    nodes,
                    new_parent_step_id,
                    ambiguous_code="AMBIGUOUS_PARENT_STEP_ID",
                )
                parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                try:
                    rec = check_admission(conn, p.uuid, "step", target.uuid, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    if frozen_at_or_below(nodes, target.uuid):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                # Membership invariant (C-007): moving a step INTO a frozen
                # subtree was previously unchecked entirely -- only the
                # moved step's own admission was verified above, never the
                # new parent's. A step is frozen_at_or_below (frozen itself
                # or has a frozen descendant) or has a frozen_ancestor
                # (a frozen step strictly above it) only under an
                # already-admitted cascade (rec is not None here whenever
                # cascade_uuid legitimately matched the plan's open cascade,
                # since the try/except above would otherwise have returned
                # CASCADE_CONFLICT before this line is reached).
                if rec is None and (
                    frozen_at_or_below(nodes, new_parent.uuid)
                    or frozen_ancestor(nodes, new_parent.uuid)
                ):
                    return domain_error(
                        "FROZEN_ARTIFACT",
                        f"new parent {new_parent.step_id} is frozen at or below the "
                        "change point, or has a frozen ancestor",
                    )
                old_step_id = target.step_id
                moved = move_step(conn, target.uuid, new_parent.uuid)
                nodes_after = load_steps(conn, p.uuid)
                snapshot = step_snapshot(moved, moved.status)
                if rec is not None:
                    status_updates = step_invalidation(nodes_after, target.uuid)
                    revision = cascade_write(
                        conn, p.uuid, rec, target.uuid, snapshot, status_updates, "api",
                        f"step_move: {moved.step_id}",
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_move: {moved.step_id}",
                        [(target.uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                    )
                verified = get_step(conn, target.uuid)
                data = {
                    "uuid": str(verified.uuid),
                    "old_step_id": old_step_id,
                    "new_step_id": verified.step_id,
                    "parent_step_uuid": str(verified.parent_step_uuid) if verified.parent_step_uuid is not None else None,
                    "path": artifact_path_of(nodes_after, verified),
                    "status": verified.status,
                    "revision_uuid": str(revision),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_move.

        Returns:
            The dict produced by `get_step_move_metadata(cls)`.
        """
        return get_step_move_metadata(cls)
