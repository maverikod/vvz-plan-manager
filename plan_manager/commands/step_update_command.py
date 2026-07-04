"""Command: patch level-specific fields of an existing step."""

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_update_metadata import get_step_update_metadata
from plan_manager.domain.step_store import get_step, update_step_fields
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


class StepUpdateCommand(Command):
    """Patch level-specific fields of an existing step under its schema."""

    name: ClassVar[str] = "step_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch level-specific fields of an existing step, re-validating touched references."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_update.

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
                    "description": "Human-readable identifier of the step to patch.",
                },
                "fields": {
                    "type": "object",
                    "description": "Non-empty level-specific field patch applied to the step's fields dict.",
                    "additionalProperties": True,
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                },
            },
            "required": ["plan", "step_id", "fields"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_update parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            ValueError: If fields is empty or if cascade_uuid is not a valid
                UUID string.
        """
        params = super().validate_params(params)
        fields = params.get("fields")
        if not fields:
            raise ValueError("fields must be a non-empty object")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(
        self,
        plan: str,
        step_id: str,
        fields: dict[str, Any],
        cascade_uuid: str | None = None,
    ) -> SuccessResult | ErrorResult:
        """Patch level-specific fields of an existing step and record it.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable identifier of the step to patch.
            fields: Non-empty level-specific field patch.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.

        Returns:
            SuccessResult with the patched step's identity, fields, status,
            and revision_uuid on success, or ErrorResult with a stable
            domain error code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = next((s for s in nodes.values() if s.step_id == step_id), None)
                if target is None:
                    raise DomainCommandError("STEP_NOT_FOUND", f"step not found: {step_id}")
                parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                try:
                    rec = check_admission(conn, p.uuid, "step", target.uuid, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    if frozen_at_or_below(nodes, target.uuid):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                update_step_fields(conn, target.uuid, fields)
                patched = get_step(conn, target.uuid)
                snapshot = step_snapshot(patched, patched.status)
                if rec is not None:
                    status_updates = step_invalidation(load_steps(conn, p.uuid), target.uuid)
                    revision = cascade_write(
                        conn, p.uuid, rec, target.uuid, snapshot, status_updates, "api",
                        f"step_update: {patched.step_id}",
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_update: {patched.step_id}",
                        [(target.uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                    )
                verified = get_step(conn, target.uuid)
                data = {
                    "uuid": str(verified.uuid),
                    "step_id": verified.step_id,
                    "fields": verified.fields,
                    "status": verified.status,
                    "revision_uuid": str(revision),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_update.

        Returns:
            The dict produced by `get_step_update_metadata(cls)`.
        """
        return get_step_update_metadata(cls)
