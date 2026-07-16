"""Command: delete a step, defaulting to a dry-run impact preview."""

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, cascade_write_many, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_delete_metadata import get_step_delete_metadata
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.domain.step_ops import delete_step, delete_subtree
from plan_manager.domain.step_store import get_step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import impact_set, load_steps


class StepDeleteCommand(Command):
    """Delete a step, defaulting to a dry-run impact preview."""

    name: ClassVar[str] = "step_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a step, with a dry-run impact preview enabled by default."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_delete.

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
                    "description": "Human-readable identifier of the step to delete.",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "When true (the default), report the delete's impact without writing anything. Set to false to perform the deletion.",
                    "default": True,
                },
                "recursive": {
                    "type": "boolean",
                    "description": "When true, delete the target step's entire subtree (the target and every transitive descendant) as one atomic revision instead of refusing when children exist. Defaults to false, which preserves the refuse-when-children behavior.",
                    "default": False,
                },
            },
            "required": ["plan", "step_id"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_delete parameters beyond the base schema check.

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
        cascade_uuid: str | None = None,
        dry_run: bool = True,
        recursive: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a step, or preview its deletion impact when dry_run is true.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable identifier of the step to delete.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.
            dry_run: When True (the default), report the impact without
                writing anything; when False, perform the deletion.
            recursive: When True, delete the target step's entire
                subtree (the target and every transitive descendant) as
                one atomic revision, instead of refusing when children
                exist. Defaults to False.

        Returns:
            SuccessResult with a dry-run impact report or the confirmed
            deletion result on success, or ErrorResult with a stable domain
            error code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                target = resolve_step_ref(nodes, step_id)
                if dry_run:
                    status_updates = step_invalidation(nodes, target.uuid)
                    impact = []
                    for node_uuid, _new_status in status_updates:
                        node = nodes.get(node_uuid)
                        if node is not None:
                            impact.append(artifact_path_of(nodes, node))
                    if recursive:
                        subtree_uuids = impact_set(nodes, target.uuid)
                        would_delete = [artifact_path_of(nodes, target)] + [
                            artifact_path_of(nodes, nodes[descendant_uuid])
                            for descendant_uuid in subtree_uuids
                        ]
                    else:
                        would_delete = artifact_path_of(nodes, target)
                    data = {
                        "dry_run": True,
                        "recursive": recursive,
                        "would_delete": would_delete,
                        "impact": impact,
                    }
                    return SuccessResult(data=data)
                if not recursive and any(s.parent_step_uuid == target.uuid for s in nodes.values()):
                    return domain_error(
                        "INVALID_TRANSITION",
                        f"step {step_id} has children; delete or move them first",
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
                target_uuid = target.uuid
                target_step_id = target.step_id
                if recursive:
                    deleted_steps = delete_subtree(conn, target_uuid)
                    node_changes: list[tuple[uuid.UUID, dict]] = []
                    for deleted in deleted_steps:
                        deleted_snapshot = step_snapshot(deleted, deleted.status)
                        deleted_snapshot["deleted"] = True
                        node_changes.append((deleted.uuid, deleted_snapshot))
                    empty_status_updates: list[tuple[uuid.UUID, str]] = []
                    message = f"step_delete(recursive): {target_step_id}"
                    if rec is not None:
                        revision = cascade_write_many(
                            conn, p.uuid, rec, node_changes, empty_status_updates, "api", message,
                        )
                    else:
                        revision = record_revision(
                            conn, p.uuid, "api", message, node_changes, p.head_revision_uuid, ref_name=None,
                        )
                    try:
                        get_step(conn, target_uuid)
                    except (DomainCommandError, ValueError):
                        deleted = True
                    else:
                        raise DomainCommandError(
                            "STEP_NOT_FOUND",
                            f"delete verification failed: step still present: {target_step_id}",
                        )
                    if not deleted:
                        raise DomainCommandError(
                            "STEP_NOT_FOUND",
                            f"delete verification failed: step still present: {target_step_id}",
                        )
                    data = {
                        "dry_run": False,
                        "recursive": True,
                        "deleted_step_id": target_step_id,
                        "deleted_step_ids": [deleted.step_id for deleted in deleted_steps],
                        "revision_uuid": str(revision),
                    }
                    return SuccessResult(data=data)
                status_updates = step_invalidation(nodes, target.uuid)
                snapshot = step_snapshot(target, target.status)
                snapshot["deleted"] = True
                delete_step(conn, target_uuid)
                if rec is not None:
                    revision = cascade_write(
                        conn, p.uuid, rec, target_uuid, snapshot, status_updates, "api",
                        f"step_delete: {target_step_id}",
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_delete: {target_step_id}",
                        [(target_uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                    )
                try:
                    get_step(conn, target_uuid)
                except (DomainCommandError, ValueError):
                    deleted = True
                else:
                    raise DomainCommandError(
                        "STEP_NOT_FOUND",
                        f"delete verification failed: step still present: {target_step_id}",
                    )
                if not deleted:
                    raise DomainCommandError(
                        "STEP_NOT_FOUND",
                        f"delete verification failed: step still present: {target_step_id}",
                    )
                data = {
                    "dry_run": False,
                    "recursive": False,
                    "deleted_step_id": target_step_id,
                    "revision_uuid": str(revision),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_delete.

        Returns:
            The dict produced by `get_step_delete_metadata(cls)`.
        """
        return get_step_delete_metadata(cls)
