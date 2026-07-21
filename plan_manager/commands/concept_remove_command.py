"""Command: remove an existing concept from the plan MRS (concept_remove)."""

import uuid

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_remove_metadata import get_concept_remove_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.cascade.write import cascade_write
from plan_manager.domain.concept_store import get_concept, remove_concept
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class ConceptRemoveCommand(Command):
    """Remove an existing MRS concept (C-003) under an open cascade (C-016).

    MRS entities are cascade-only at any plan status: every call must carry the
    UUID of an already-open cascade in cascade_uuid.
    """

    name = "concept_remove"
    version = "1.0.0"
    descr = "Remove an existing concept from the plan MRS under an open cascade."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_remove."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to resolve.",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "UUID of the open cascade admitting this mutation. Required: MRS entities are cascade-only at any status.",
                },
                "concept_id": {
                    "type": "string",
                    "description": "Concept identifier of the concept to remove.",
                },
            },
            "required": ["plan", "cascade_uuid", "concept_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_concept_remove_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate params: shallow schema checks, then parse cascade_uuid format.

        Raises:
            ValueError: if cascade_uuid is not a well-formed UUID string.
        """
        params = super().validate_params(params)
        uuid.UUID(params["cascade_uuid"])
        return params

    async def execute(
        self,
        plan: str,
        cascade_uuid: str,
        concept_id: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Remove concept_id under an open cascade and verify by re-read.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            cascade_uuid: UUID string of the open cascade admitting this mutation.
            concept_id: Concept identifier of the concept to remove.

        Returns:
            SuccessResult with concept_id, deleted: true, and revision_uuid, or
            ErrorResult with code PLAN_NOT_FOUND, CASCADE_CONFLICT, or
            CONCEPT_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                parsed_cascade = uuid.UUID(cascade_uuid)
                try:
                    rec = check_admission(conn, p.uuid, "concept", None, parsed_cascade)
                except CascadeError as exc:
                    return domain_error("CASCADE_CONFLICT", str(exc))
                row = conn.execute(
                    "SELECT uuid FROM concept WHERE plan_uuid = %s AND concept_id = %s",
                    (p.uuid, concept_id),
                ).fetchone()
                row_uuid = row[0] if row else None
                if row_uuid is None:
                    return domain_error(
                        "CONCEPT_NOT_FOUND",
                        f"concept not found: {concept_id}",
                    )
                try:
                    removed = remove_concept(conn, p.uuid, concept_id)
                except ValueError as exc:
                    return domain_error("CONCEPT_NOT_FOUND", str(exc))
                nodes = load_steps(conn, p.uuid)
                status_updates = [
                    (step.uuid, "needs_review")
                    for step in sorted(nodes.values(), key=lambda step: step.step_id)
                    if step.level == 3
                ]
                snapshot = {
                    "kind": "concept",
                    "uuid": str(row_uuid),
                    "plan_uuid": str(p.uuid),
                    "concept_id": removed.concept_id,
                    "name": removed.name,
                    "definition": removed.definition,
                    "properties": removed.properties,
                    "source_labels": removed.source_labels,
                    "deleted": True,
                }
                revision_uuid = cascade_write(
                    conn,
                    p.uuid,
                    rec,
                    row_uuid,
                    snapshot,
                    status_updates,
                    "api",
                    f"concept_remove: {removed.concept_id}",
                )
                if get_concept(conn, p.uuid, concept_id) is not None:
                    raise RuntimeError("concept_remove: write verification failed")
                return SuccessResult(data={
                    "concept_id": removed.concept_id,
                    "deleted": True,
                    "revision_uuid": str(revision_uuid),
                })
        except Exception as exc:
            return map_exception(exc)
