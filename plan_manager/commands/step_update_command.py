"""Command: patch level-specific fields of an existing step."""

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.cascade.propagation import step_invalidation
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_ref import resolve_step_ref
from plan_manager.commands.step_update_metadata import get_step_update_metadata
from plan_manager.domain.concept import CONCEPT_ID_PATTERN
from plan_manager.domain.concept_store import list_concept_ids
from plan_manager.domain.relation import RELATION_TYPES
from plan_manager.domain.project_binding import require_project_bound
from plan_manager.domain.step_store import (
    get_step,
    update_step_fields_and_concepts,
    update_step_fields_concepts_project,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


_RELATION_KEYS = frozenset({"type", "from_concept", "to_concept"})
_PROJECT_ID_UNSET = object()


def _validate_concept_bindings(concepts: Any) -> list[str]:
    if not isinstance(concepts, list):
        raise DomainCommandError(
            "INVALID_STEP_FIELD_SHAPE",
            "concepts must be a list of concept_id strings",
            {"field": "concepts"},
        )
    seen: set[str] = set()
    result: list[str] = []
    for index, concept_id in enumerate(concepts):
        if not isinstance(concept_id, str) or not CONCEPT_ID_PATTERN.match(concept_id):
            raise DomainCommandError(
                "INVALID_STEP_FIELD_SHAPE",
                "concepts entries must be concept_id strings like C-001",
                {"field": "concepts", "index": index},
            )
        if concept_id in seen:
            raise DomainCommandError(
                "INVALID_STEP_FIELD_SHAPE",
                "concepts entries must be unique",
                {"field": "concepts", "concept_id": concept_id},
            )
        seen.add(concept_id)
        result.append(concept_id)
    return result


def _validate_relations_field(fields: dict[str, Any]) -> list[dict[str, str]] | None:
    if "relations" not in fields:
        return None
    relations = fields["relations"]
    if not isinstance(relations, list):
        raise DomainCommandError(
            "INVALID_STEP_FIELD_SHAPE",
            "fields.relations must be a list of relation objects",
            {"field": "fields.relations"},
        )
    result: list[dict[str, str]] = []
    for index, entry in enumerate(relations):
        if not isinstance(entry, dict) or set(entry) != _RELATION_KEYS:
            raise DomainCommandError(
                "INVALID_STEP_FIELD_SHAPE",
                "each fields.relations entry must contain type, from_concept, and to_concept",
                {"field": "fields.relations", "index": index},
            )
        relation_type = entry["type"]
        from_concept = entry["from_concept"]
        to_concept = entry["to_concept"]
        if relation_type not in RELATION_TYPES:
            raise DomainCommandError(
                "INVALID_STEP_FIELD_SHAPE",
                "fields.relations entry has an invalid relation type",
                {"field": "fields.relations", "index": index, "type": relation_type},
            )
        for key, value in (("from_concept", from_concept), ("to_concept", to_concept)):
            if not isinstance(value, str) or not CONCEPT_ID_PATTERN.match(value):
                raise DomainCommandError(
                    "INVALID_STEP_FIELD_SHAPE",
                    "fields.relations endpoints must be concept_id strings like C-001",
                    {"field": f"fields.relations.{key}", "index": index},
                )
        result.append(
            {"type": relation_type, "from_concept": from_concept, "to_concept": to_concept}
        )
    return result


def _ensure_concepts_exist(
    existing_concepts: set[str],
    concepts: list[str],
    *,
    field: str,
) -> None:
    missing = sorted(set(concepts) - existing_concepts)
    if missing:
        raise DomainCommandError(
            "CONCEPT_NOT_FOUND",
            "concept not found",
            {"field": field, "missing_concepts": missing},
        )


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
                "concepts": {
                    "type": "array",
                    "description": "Optional complete replacement for the step's top-level concept_id bindings.",
                    "items": {"type": "string"},
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen target.",
                },
                "project_id": {
                    "type": "string",
                    "nullable": True,
                    "description": "Optional top-level analysis-server project UUID; null clears the step binding.",
                },
            },
            "required": ["plan", "step_id"],
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
        raw_project_present = "project_id" in params
        raw_project_clear = raw_project_present and params["project_id"] is None
        validation_params = dict(params)
        if raw_project_clear:
            validation_params.pop("project_id")
        params = super().validate_params(validation_params)
        if raw_project_clear:
            params["project_id"] = None
        fields = params.get("fields")
        concepts_present = "concepts" in params
        project_present = "project_id" in params
        if fields is None and not concepts_present and not project_present:
            raise ValueError("fields, concepts, or project_id must be supplied")
        if fields is not None and (not isinstance(fields, dict) or not fields):
            raise ValueError("fields must be a non-empty object when supplied")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(
        self,
        plan: str,
        step_id: str,
        fields: dict[str, Any] | None = None,
        concepts: list[str] | None = None,
        project_id: Any = _PROJECT_ID_UNSET,
        cascade_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Patch level-specific fields of an existing step and record it.

        Args:
            plan: Plan identifier (UUID or name).
            step_id: Human-readable identifier of the step to patch.
            fields: Optional non-empty level-specific field patch.
            concepts: Optional complete replacement for top-level
                concept_id bindings.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.

        Returns:
            SuccessResult with the patched step's identity, fields, status,
            and revision_uuid on success, or ErrorResult with a stable
            domain error code on failure.
        """
        try:
            project_present = project_id is not _PROJECT_ID_UNSET
            if fields is None and concepts is None and not project_present:
                raise DomainCommandError(
                    "INVALID_STEP_FIELD_SHAPE",
                    "fields, concepts, or project_id must be supplied",
                    {},
                )
            if fields is not None and (not isinstance(fields, dict) or not fields):
                raise DomainCommandError(
                    "INVALID_STEP_FIELD_SHAPE",
                    "fields must be a non-empty object when supplied",
                    {"field": "fields"},
                )
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if project_present and project_id is not None:
                    normalized_project_id = require_project_bound(p, project_id)
                elif project_present:
                    normalized_project_id = None
                else:
                    normalized_project_id = None
                nodes = load_steps(conn, p.uuid)
                target = resolve_step_ref(nodes, step_id)
                fields = fields or {}
                existing_concepts = set(list_concept_ids(conn, p.uuid))
                relation_entries = _validate_relations_field(fields)
                if relation_entries is not None:
                    relation_concepts = [
                        concept_id
                        for entry in relation_entries
                        for concept_id in (entry["from_concept"], entry["to_concept"])
                    ]
                    _ensure_concepts_exist(
                        existing_concepts,
                        relation_concepts,
                        field="fields.relations",
                    )
                new_concepts = (
                    _validate_concept_bindings(concepts)
                    if concepts is not None
                    else list(target.concepts)
                )
                _ensure_concepts_exist(existing_concepts, new_concepts, field="concepts")
                parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                try:
                    rec = check_admission(conn, p.uuid, "step", target.uuid, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    if frozen_at_or_below(nodes, target.uuid):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                merged_fields = dict(target.fields)
                merged_fields.update(fields)
                if project_present:
                    update_step_fields_concepts_project(
                        conn, target.uuid, merged_fields, new_concepts, normalized_project_id
                    )
                else:
                    update_step_fields_and_concepts(conn, target.uuid, merged_fields, new_concepts)
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
                    "concepts": verified.concepts,
                    "project_id": verified.project_id,
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
