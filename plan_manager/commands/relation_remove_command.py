"""Command: remove an existing relation between two concepts (relation_remove)."""

import uuid

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.relation_remove_metadata import get_relation_remove_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.cascade.write import cascade_write
from plan_manager.domain.relation_store import remove_relation, list_relations
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps

_RELATION_TYPES = [
    "uses",
    "owns",
    "implements",
    "extends",
    "depends_on",
    "produces",
    "consumes",
]


class RelationRemoveCommand(Command):
    """Remove an existing MRS relation (C-004) under an open cascade (C-016).

    MRS entities are cascade-only at any plan status: every call must carry the
    UUID of an already-open cascade in cascade_uuid.
    """

    name = "relation_remove"
    version = "1.0.0"
    descr = "Remove an existing relation between two concepts under an open cascade."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for relation_remove."""
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
                "from_concept": {
                    "type": "string",
                    "description": "Concept identifier of the relation source endpoint.",
                },
                "to_concept": {
                    "type": "string",
                    "description": "Concept identifier of the relation target endpoint.",
                },
                "type": {
                    "type": "string",
                    "enum": _RELATION_TYPES,
                    "description": "Relation type; one of the seven allowed types.",
                },
            },
            "required": ["plan", "cascade_uuid", "from_concept", "to_concept", "type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_relation_remove_metadata(cls)

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
        from_concept: str,
        to_concept: str,
        type: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Remove an existing relation under an open cascade and verify by re-read.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            cascade_uuid: UUID string of the open cascade admitting this mutation.
            from_concept: Concept identifier of the relation source endpoint.
            to_concept: Concept identifier of the relation target endpoint.
            type: Relation type; one of the seven allowed types.

        Returns:
            SuccessResult with from_concept, to_concept, type, deleted: true,
            and revision_uuid, or ErrorResult with code PLAN_NOT_FOUND,
            CASCADE_CONFLICT, or RELATION_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                parsed_cascade = uuid.UUID(cascade_uuid)
                try:
                    rec = check_admission(conn, p.uuid, "relation", None, parsed_cascade)
                except CascadeError as exc:
                    return domain_error("CASCADE_CONFLICT", str(exc))
                try:
                    relation_uuid = remove_relation(conn, p.uuid, from_concept, to_concept, type)
                except ValueError:
                    return domain_error(
                        "RELATION_NOT_FOUND",
                        f"relation not found: {from_concept}-{type}->{to_concept}",
                    )
                nodes = load_steps(conn, p.uuid)
                status_updates = [
                    (step.uuid, "needs_review")
                    for step in sorted(nodes.values(), key=lambda step: step.step_id)
                    if step.level == 3
                ]
                snapshot = {
                    "kind": "relation",
                    "uuid": str(relation_uuid),
                    "plan_uuid": str(p.uuid),
                    "from_concept": from_concept,
                    "to_concept": to_concept,
                    "type": type,
                    "deleted": True,
                }
                revision_uuid = cascade_write(
                    conn,
                    p.uuid,
                    rec,
                    relation_uuid,
                    snapshot,
                    status_updates,
                    "api",
                    f"relation_remove: {from_concept}-{type}->{to_concept}",
                )
                remaining = any(
                    r == (from_concept, to_concept, type)
                    for r in list_relations(conn, p.uuid)
                )
                if remaining:
                    raise RuntimeError("relation_remove: write verification failed")
                return SuccessResult(data={
                    "from_concept": from_concept,
                    "to_concept": to_concept,
                    "type": type,
                    "deleted": True,
                    "revision_uuid": str(revision_uuid),
                })
        except Exception as exc:
            return map_exception(exc)
