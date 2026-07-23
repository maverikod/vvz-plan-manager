"""Command: update fields of an existing concept (concept_update)."""

import uuid

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.concept_update_metadata import get_concept_update_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.cascade.write import cascade_write
from plan_manager.domain.concept import ConceptValidationError
from plan_manager.domain.concept_store import get_concept, update_concept
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps

_UPDATABLE_FIELDS = {"name", "definition", "properties", "source_labels"}


class ConceptUpdateCommand(Command):
    """Update fields of an existing MRS concept (C-003) under an open cascade (C-016).

    MRS entities are cascade-only at any plan status: every call must carry the
    UUID of an already-open cascade in cascade_uuid.
    """

    name = "concept_update"
    version = "1.0.0"
    descr = "Update fields of an existing concept under an open cascade."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_update."""
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
                    "description": "Concept identifier of the concept to update.",
                },
                "fields": {
                    "type": "object",
                    "description": "Partial field set to update. Keys must be a non-empty subset of name, definition, properties, source_labels.",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "New concept canonical name.",
                        },
                        "definition": {
                            "type": "string",
                            "description": "New concept one-sentence definition.",
                        },
                        "properties": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New free-form property statements.",
                        },
                        "source_labels": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "New HRS paragraph labels; each must resolve to a stored binding paragraph.",
                        },
                    },
                    "required": [],
                },
            },
            "required": ["plan", "cascade_uuid", "concept_id", "fields"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_concept_update_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate params: shallow schema checks, cascade_uuid format, and fields semantics.

        Raises:
            InvalidParamsError: if cascade_uuid is not a well-formed UUID
                string, or if fields is not a non-empty dict whose keys are
                a subset of {"name", "definition", "properties",
                "source_labels"}.
        """
        params = super().validate_params(params)
        cascade_uuid = params["cascade_uuid"]
        try:
            uuid.UUID(cascade_uuid)
        except ValueError as exc:
            raise InvalidParamsError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
        fields = params.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise InvalidParamsError("fields must be a non-empty object")
        extra = set(fields.keys()) - _UPDATABLE_FIELDS
        if extra:
            raise InvalidParamsError(f"fields contains unsupported keys: {sorted(extra)}")
        return params

    async def execute(
        self,
        plan: str,
        cascade_uuid: str,
        concept_id: str,
        fields: dict,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Apply fields to an existing concept under an open cascade and verify by re-read.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            cascade_uuid: UUID string of the open cascade admitting this mutation.
            concept_id: Concept identifier of the concept to update.
            fields: Partial field set to update (keys already validated in
                validate_params to be a non-empty subset of name, definition,
                properties, source_labels).

        Returns:
            SuccessResult with the updated concept fields plus revision_uuid, or
            ErrorResult with code PLAN_NOT_FOUND, CASCADE_CONFLICT,
            CONCEPT_NOT_FOUND, or PARAGRAPH_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                parsed_cascade = uuid.UUID(cascade_uuid)
                try:
                    rec = check_admission(conn, p.uuid, "concept", None, parsed_cascade)
                except CascadeError as exc:
                    return domain_error("CASCADE_CONFLICT", str(exc))
                if "source_labels" in fields:
                    stored = {row.label for row in list_paragraphs(conn, p.uuid) if row.label is not None}
                    for label in fields["source_labels"]:
                        bare = label.strip("{}")
                        if bare not in stored:
                            return domain_error(
                                "PARAGRAPH_NOT_FOUND",
                                f"source label does not resolve: {label}",
                                {"field": "source_labels", "label": label},
                            )
                try:
                    updated = update_concept(conn, p.uuid, concept_id, fields)
                except ConceptValidationError as exc:
                    return domain_error("IMPORT_INVALID", str(exc), {"field": "fields"})
                except ValueError as exc:
                    msg = str(exc)
                    if msg.startswith("concept not found"):
                        return domain_error("CONCEPT_NOT_FOUND", msg)
                    return domain_error("IMPORT_INVALID", msg, {"field": "fields"})
                row = conn.execute(
                    "SELECT uuid FROM concept WHERE plan_uuid = %s AND concept_id = %s",
                    (p.uuid, updated.concept_id),
                ).fetchone()
                row_uuid = row[0] if row else None
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
                    "concept_id": updated.concept_id,
                    "name": updated.name,
                    "definition": updated.definition,
                    "properties": updated.properties,
                    "source_labels": updated.source_labels,
                }
                revision_uuid = cascade_write(
                    conn,
                    p.uuid,
                    rec,
                    row_uuid,
                    snapshot,
                    status_updates,
                    "api",
                    f"concept_update: {updated.concept_id}",
                )
                verified = get_concept(conn, p.uuid, concept_id)
                if verified is None:
                    raise RuntimeError("concept_update: write verification failed")
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
