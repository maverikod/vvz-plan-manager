"""Command: add a new concept to the plan MRS (concept_add)."""

import uuid

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_add_metadata import get_concept_add_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.cascade.write import cascade_write
from plan_manager.domain.concept import Concept, ConceptValidationError
from plan_manager.domain.concept_store import get_concept, insert_concept
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps


class ConceptAddCommand(Command):
    """Add a new MRS concept (C-003) to a resolved plan under an open cascade (C-016).

    MRS entities are cascade-only at any plan status: every call must carry the
    UUID of an already-open cascade in cascade_uuid.
    """

    name = "concept_add"
    version = "1.0.0"
    descr = "Add a new concept to the plan MRS under an open cascade."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_add."""
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
                    "description": "Concept identifier in pattern C-NNN. Must be unique within the plan.",
                },
                "name": {
                    "type": "string",
                    "description": "Concept canonical name.",
                },
                "definition": {
                    "type": "string",
                    "description": "Concept one-sentence definition.",
                },
                "properties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Free-form property statements of the concept.",
                },
                "source_labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "HRS paragraph labels (four-character base36) that justify this concept; each must resolve to a stored binding paragraph.",
                },
            },
            "required": ["plan", "cascade_uuid", "concept_id", "name", "definition"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_concept_add_metadata(cls)

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
        name: str,
        definition: str,
        properties: list[str] | None = None,
        source_labels: list[str] | None = None,
    ) -> SuccessResult | ErrorResult:
        """Add a new concept under an open cascade and verify by re-read.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            cascade_uuid: UUID string of the open cascade admitting this mutation.
            concept_id: New concept identifier in pattern C-NNN.
            name: Concept canonical name.
            definition: Concept one-sentence definition.
            properties: Free-form property statements; defaults to [] when omitted.
            source_labels: HRS paragraph labels justifying the concept; defaults
                to [] when omitted.

        Returns:
            SuccessResult with the written concept fields plus revision_uuid, or
            ErrorResult with code PLAN_NOT_FOUND, CASCADE_CONFLICT,
            DUPLICATE_ID, or PARAGRAPH_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                parsed_cascade = uuid.UUID(cascade_uuid)
                try:
                    rec = check_admission(conn, p.uuid, "concept", None, parsed_cascade)
                except CascadeError as exc:
                    return domain_error("CASCADE_CONFLICT", str(exc))
                resolved_labels = source_labels or []
                stored = {row.label for row in list_paragraphs(conn, p.uuid) if row.label is not None}
                for label in resolved_labels:
                    bare = label.strip("{}")
                    if bare not in stored:
                        return domain_error(
                            "PARAGRAPH_NOT_FOUND",
                            f"source label does not resolve: {label}",
                            {"field": "source_labels", "label": label},
                        )
                concept = Concept(
                    concept_id=concept_id,
                    name=name,
                    definition=definition,
                    properties=properties or [],
                    source_labels=resolved_labels,
                )
                try:
                    row_uuid = insert_concept(conn, p.uuid, concept)
                except ConceptValidationError as exc:
                    msg = str(exc)
                    if "unique" in msg:
                        return domain_error(
                            "DUPLICATE_ID",
                            msg,
                            {"field": "concept_id", "concept_id": concept_id},
                        )
                    return domain_error("IMPORT_INVALID", msg, {"field": "concept"})
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
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "definition": concept.definition,
                    "properties": concept.properties,
                    "source_labels": concept.source_labels,
                }
                revision_uuid = cascade_write(
                    conn,
                    p.uuid,
                    rec,
                    row_uuid,
                    snapshot,
                    status_updates,
                    "api",
                    f"concept_add: {concept.concept_id}",
                )
                verified = get_concept(conn, p.uuid, concept.concept_id)
                if verified is None:
                    raise RuntimeError("concept_add: write verification failed")
                return SuccessResult(data={
                    "uuid": str(row_uuid),
                    "plan_uuid": str(p.uuid),
                    "concept_id": verified.concept_id,
                    "name": verified.name,
                    "definition": verified.definition,
                    "properties": verified.properties,
                    "source_labels": verified.source_labels,
                    "revision_uuid": str(revision_uuid),
                })
        except Exception as exc:
            return map_exception(exc)
