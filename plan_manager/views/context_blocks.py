"""Authoring context-block compilation and derived-record storage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.cascade.record import get_open_cascade
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.domain.concept_store import list_concepts
from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.plan import Plan
from plan_manager.domain.plan_schema import default_plan_schema
from plan_manager.domain.relation_store import list_relations
from plan_manager.storage.canonical import content_hash
from plan_manager.storage.version_store import get_ref
from plan_manager.views.dependency_graph import load_steps


TEMPLATE_VERSION = "2026-07-06.context-blocks.v1"
TIER_BY_LEVEL = {3: "global", 4: "mid", 5: "atomic"}

# Nested item contract for the level-4 (TS) fields.inputs / fields.outputs
# lists (bug ad529347): each list holds JSON objects, never bare strings, so
# a client cannot derive this shape from the flat required_fields name list
# alone. Shared verbatim by _field_schema_block below and by
# plan_manager.commands.info_reference.planning_standards_reference so the
# nested contract is documented identically everywhere it is surfaced.
TS_INPUT_OUTPUT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["name", "type", "description"],
    "properties": {
        "name": "Non-empty stable kebab-case identifier string for the item.",
        "type": 'Non-empty string; must be one of "input" or "output".',
        "description": "Non-empty human-readable string describing the item.",
    },
    "example_valid": {"name": "source-file-path", "type": "input", "description": "Path to the file being read."},
    "example_invalid": ["source-file-path"],
}
ORDER = {
    "authoring_template": 0,
    "standards": 1,
    "field_schema": 2,
    "step_definition": 3,
    "hrs_fragment": 4,
    "mrs_concept": 5,
    "mrs_relation": 6,
}


@dataclass(frozen=True)
class ContextRevision:
    revision_uuid: uuid.UUID | None
    cascade_uuid: uuid.UUID | None


@dataclass(frozen=True)
class ContextBlockRecord(DataclassEntity):
    ENTITY_TYPE = "context_block"
    ENTITY_ID_FIELD = "block_id"
    TABLE_NAME = "context_block"
    SOFT_DELETE_COLUMN = None

    block_id: uuid.UUID
    plan_uuid: uuid.UUID
    revision_uuid: uuid.UUID | None
    cascade_uuid: uuid.UUID | None
    node_path: str
    child_level: int
    kind: str
    common_block_id: uuid.UUID | None
    scope_concepts: list[str]
    content: list[dict[str, Any]]
    content_hash: str
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "block_id": str(self.block_id),
            "plan_uuid": str(self.plan_uuid),
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid else None,
            "cascade_uuid": str(self.cascade_uuid) if self.cascade_uuid else None,
            "node_path": self.node_path,
            "child_level": self.child_level,
            "kind": self.kind,
            "common_block_id": str(self.common_block_id) if self.common_block_id else None,
            "scope_concepts": list(self.scope_concepts),
            "content_hash": self.content_hash,
            "hash": self.content_hash,
            "blocks": list(self.content),
            "content": list(self.content),
            "created_at": self.created_at,
        }


def validate_child_level(child_level: int) -> None:
    if child_level not in (3, 4, 5):
        raise DomainCommandError(
            "INVALID_LEVEL",
            f"child_level must be one of [3, 4, 5], got {child_level!r}",
            {"child_level": child_level},
        )


def resolve_context_revision(
    conn: psycopg.Connection,
    plan: Plan,
    revision: str | None = None,
    cascade_uuid: str | None = None,
) -> ContextRevision:
    if revision is not None and cascade_uuid is not None:
        raise DomainCommandError(
            "CASCADE_CONFLICT",
            "revision and cascade_uuid are mutually exclusive",
        )
    if cascade_uuid is not None:
        try:
            requested = uuid.UUID(cascade_uuid)
        except ValueError as exc:
            raise DomainCommandError("CASCADE_CONFLICT", f"invalid cascade_uuid: {cascade_uuid}") from exc
        cascade = get_open_cascade(conn, plan.uuid)
        if cascade is None or cascade.uuid != requested:
            raise DomainCommandError(
                "CASCADE_CONFLICT",
                "supplied cascade_uuid is not the plan's open cascade",
                {"cascade_uuid": cascade_uuid},
            )
        return ContextRevision(get_ref(conn, plan.uuid, cascade.name), cascade.uuid)
    if revision is None:
        return ContextRevision(plan.head_revision_uuid, None)
    try:
        requested_revision = uuid.UUID(revision)
    except ValueError as exc:
        raise DomainCommandError("REVISION_NOT_FOUND", f"revision not found: {revision}") from exc
    row = conn.execute(
        "SELECT 1 FROM revision WHERE plan_uuid = %s AND uuid = %s",
        (plan.uuid, requested_revision),
    ).fetchone()
    if row is None or requested_revision != plan.head_revision_uuid:
        raise DomainCommandError(
            "REVISION_NOT_FOUND",
            f"revision not available for live context compilation: {revision}",
            {"current_head_revision": str(plan.head_revision_uuid) if plan.head_revision_uuid else None},
        )
    return ContextRevision(requested_revision, None)


def _dedupe(values: list[str]) -> list[str]:
    return sorted(set(values))


def _normalize_label(label: str) -> str:
    return label[1:-1] if label.startswith("{") and label.endswith("}") else label


def _block_sort_key(block: dict[str, Any]) -> tuple:
    block_type = block["type"]
    if block_type == "hrs_fragment":
        identity = block["label"]
    elif block_type == "mrs_concept":
        identity = block["concept_id"]
    elif block_type == "mrs_relation":
        identity = (block["from_concept"], block["to_concept"], block["relation_type"])
    elif block_type == "step_definition":
        identity = block["path"]
    else:
        identity = block_type
    return (ORDER[block_type], identity)


def _delta_key(block: dict[str, Any]) -> tuple | None:
    if block["type"] == "hrs_fragment":
        return ("hrs_fragment", block["label"])
    if block["type"] == "mrs_concept":
        return ("mrs_concept", block["concept_id"])
    if block["type"] == "mrs_relation":
        return (
            "mrs_relation",
            block["from_concept"],
            block["to_concept"],
            block["relation_type"],
        )
    return None


def _authoring_template(child_level: int) -> dict[str, Any]:
    tier = TIER_BY_LEVEL[child_level]
    return {
        "type": "authoring_template",
        "level": child_level,
        "tier": tier,
        "role_instructions": (
            "Author only the requested child planning artifact. Use supplied "
            "concept ids as the allowed semantic scope and preserve top-down "
            "traceability to HRS labels and MRS relations."
        ),
        "output_contract": (
            "Return a machine-readable planning artifact for the requested "
            "level with required fields populated, deterministic ids supplied "
            "by plan-manager commands, and no prose outside the artifact body."
        ),
        "template_version": TEMPLATE_VERSION,
    }


def _standards_block(child_level: int) -> dict[str, Any]:
    tier = TIER_BY_LEVEL[child_level]
    return {
        "type": "standards",
        "tier": tier,
        "text": (
            "Planning artifacts are authored top-down. HRS is human-owned. "
            "MRS concepts define the semantic basis. Global, tactical, and "
            "atomic steps must narrow inherited concept scope, keep references "
            "resolvable, and use cascade discipline for changes under frozen "
            "artifacts."
        ),
    }


def _field_schema_block(child_level: int) -> dict[str, Any]:
    schema = default_plan_schema()
    field_schema: dict[str, Any] = {
        "identifier_pattern": schema.identifier_patterns[child_level],
        "required_fields": schema.required_fields[child_level],
    }
    if child_level == 4:
        # bug ad529347: required_fields only names "inputs"/"outputs" as
        # bare fields; without this nested item_schemas key a client sees
        # no way to tell those are lists of {name, type, description}
        # objects (type one of "input" or "output"), not lists of strings.
        field_schema["item_schemas"] = {
            "inputs": TS_INPUT_OUTPUT_ITEM_SCHEMA,
            "outputs": TS_INPUT_OUTPUT_ITEM_SCHEMA,
        }
    return {
        "type": "field_schema",
        "level": child_level,
        "schema": field_schema,
    }


def _step_definition_block(path: str, step) -> dict[str, Any]:
    return {
        "type": "step_definition",
        "path": path,
        "name": step.fields.get("name", step.slug),
        "description": step.fields.get("description", ""),
        "fields": step.fields,
    }


def compile_plan_material(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    concepts: list[str],
) -> list[dict[str, Any]]:
    requested = _dedupe(concepts)
    concept_by_id = {concept.concept_id: concept for concept in list_concepts(conn, plan_uuid)}
    missing = [concept_id for concept_id in requested if concept_id not in concept_by_id]
    if missing:
        raise DomainCommandError(
            "CONCEPT_NOT_FOUND",
            f"concept not found: {missing[0]}",
            {"concept_ids": missing},
        )

    blocks: list[dict[str, Any]] = []
    labels: set[str] = set()
    for concept_id in requested:
        concept = concept_by_id[concept_id]
        labels.update(_normalize_label(label) for label in concept.source_labels)
        blocks.append(
            {
                "type": "mrs_concept",
                "concept_id": concept.concept_id,
                "name": concept.name,
                "definition": concept.definition,
                "properties": list(concept.properties),
            }
        )

    paragraph_by_label = {
        paragraph.label: paragraph
        for paragraph in list_paragraphs(conn, plan_uuid)
        if paragraph.label is not None
    }
    for label in sorted(labels):
        paragraph = paragraph_by_label.get(label)
        if paragraph is not None:
            blocks.append(
                {
                    "type": "hrs_fragment",
                    "label": "{" + label + "}",
                    "text": paragraph.text,
                    "position": paragraph.position,
                }
            )

    source = set(requested)
    for from_concept, to_concept, relation_type in list_relations(conn, plan_uuid):
        if from_concept in source:
            blocks.append(
                {
                    "type": "mrs_relation",
                    "from_concept": from_concept,
                    "to_concept": to_concept,
                    "relation_type": relation_type,
                }
            )
    return sorted(blocks, key=_block_sort_key)


def compile_context(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    concepts: list[str],
    child_level: int,
    include: dict[str, Any] | None = None,
    node_path: str = "plan",
) -> tuple[list[dict[str, Any]], list[str]]:
    validate_child_level(child_level)
    include = include or {}
    content: list[dict[str, Any]] = []
    if include.get("authoring_template", True):
        content.append(_authoring_template(child_level))
    if include.get("standards", True):
        content.append(_standards_block(child_level))
    if include.get("field_schema", True):
        content.append(_field_schema_block(child_level))
    if include.get("step_definition_of"):
        nodes = load_steps(conn, plan_uuid)
        step = resolve_step_ref(nodes, str(include["step_definition_of"]))
        content.append(_step_definition_block(canonical_step_path(nodes, step), step))
    content.extend(compile_plan_material(conn, plan_uuid, concepts))
    return sorted(content, key=_block_sort_key), _dedupe(concepts)


def common_context(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    node: str,
    child_level: int,
    shared_concepts: list[str] | None = None,
) -> tuple[str, list[str], list[dict[str, Any]]]:
    validate_child_level(child_level)
    nodes = load_steps(conn, plan_uuid)
    if node == "plan":
        node_path = "plan"
        concepts = shared_concepts
        if concepts is None:
            concepts = [concept.concept_id for concept in list_concepts(conn, plan_uuid)]
        step = None
    else:
        step = resolve_step_ref(nodes, node, not_found_code="NODE_NOT_FOUND")
        node_path = canonical_step_path(nodes, step)
        concepts = shared_concepts if shared_concepts is not None else list(step.concepts)

    content = [_authoring_template(child_level), _standards_block(child_level), _field_schema_block(child_level)]
    if step is not None:
        content.append(_step_definition_block(node_path, step))
    content.extend(compile_plan_material(conn, plan_uuid, concepts))
    return node_path, _dedupe(concepts), sorted(content, key=_block_sort_key)


def specific_delta(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    common: ContextBlockRecord,
    concepts: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    scope = _dedupe(concepts)
    outside = sorted(set(scope) - set(common.scope_concepts))
    if outside:
        raise DomainCommandError(
            "CONCEPT_OUT_OF_SCOPE",
            "specific concepts are outside the common block scope",
            {"concept_ids": outside, "common_block_id": str(common.block_id)},
        )
    common_delta_keys = {
        key for key in (_delta_key(block) for block in common.content) if key is not None
    }
    delta = [
        block
        for block in compile_plan_material(conn, plan_uuid, scope)
        if _delta_key(block) not in common_delta_keys
    ]
    return scope, sorted(delta, key=_block_sort_key)


def _row_to_record(row) -> ContextBlockRecord:
    return ContextBlockRecord(
        block_id=row[0],
        plan_uuid=row[1],
        revision_uuid=row[2],
        cascade_uuid=row[3],
        node_path=row[4],
        child_level=row[5],
        kind=row[6],
        common_block_id=row[7],
        scope_concepts=list(row[8]),
        content=list(row[9]),
        content_hash=row[10],
        created_at=row[11].isoformat(),
    )


def store_context_block(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    context_revision: ContextRevision,
    node_path: str,
    child_level: int,
    kind: str,
    scope_concepts: list[str],
    content: list[dict[str, Any]],
    common_block_id: uuid.UUID | None = None,
) -> ContextBlockRecord:
    hash_value = content_hash(content)
    row = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, cascade_uuid, node_path, child_level, "
        "kind, common_block_uuid, scope_concepts, content, content_hash, created_at "
        "FROM context_block WHERE plan_uuid = %s "
        "AND revision_uuid IS NOT DISTINCT FROM %s "
        "AND cascade_uuid IS NOT DISTINCT FROM %s "
        "AND node_path = %s AND child_level = %s AND kind = %s AND content_hash = %s "
        "AND common_block_uuid IS NOT DISTINCT FROM %s "
        "AND scope_concepts = %s",
        (
            plan_uuid,
            context_revision.revision_uuid,
            context_revision.cascade_uuid,
            node_path,
            child_level,
            kind,
            hash_value,
            common_block_id,
            scope_concepts,
        ),
    ).fetchone()
    if row is not None:
        return _row_to_record(row)

    block_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO context_block "
        "(uuid, plan_uuid, revision_uuid, cascade_uuid, node_path, child_level, "
        "kind, common_block_uuid, scope_concepts, content, content_hash, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            block_id,
            plan_uuid,
            context_revision.revision_uuid,
            context_revision.cascade_uuid,
            node_path,
            child_level,
            kind,
            common_block_id,
            scope_concepts,
            Jsonb(content),
            hash_value,
            created_at,
        ),
    )
    return ContextBlockRecord(
        block_id=block_id,
        plan_uuid=plan_uuid,
        revision_uuid=context_revision.revision_uuid,
        cascade_uuid=context_revision.cascade_uuid,
        node_path=node_path,
        child_level=child_level,
        kind=kind,
        common_block_id=common_block_id,
        scope_concepts=list(scope_concepts),
        content=list(content),
        content_hash=hash_value,
        created_at=created_at.isoformat(),
    )


def get_context_block(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    block_id: uuid.UUID,
) -> ContextBlockRecord:
    row = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, cascade_uuid, node_path, child_level, "
        "kind, common_block_uuid, scope_concepts, content, content_hash, created_at "
        "FROM context_block WHERE plan_uuid = %s AND uuid = %s",
        (plan_uuid, block_id),
    ).fetchone()
    if row is None:
        raise DomainCommandError(
            "COMMON_BLOCK_NOT_FOUND",
            f"context block not found: {block_id}",
            {"block_id": str(block_id)},
        )
    return _row_to_record(row)


def list_context_blocks(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    node: str | None = None,
    kind: str | None = None,
    revision: str | None = None,
    cascade_uuid: str | None = None,
) -> list[dict[str, Any]]:
    conditions = ["plan_uuid = %s"]
    params: list[Any] = [plan_uuid]
    if node is not None:
        conditions.append("node_path = %s")
        params.append(node)
    if kind is not None:
        conditions.append("kind = %s")
        params.append(kind)
    if revision is not None:
        conditions.append("revision_uuid = %s")
        params.append(uuid.UUID(revision))
    if cascade_uuid is not None:
        conditions.append("cascade_uuid = %s")
        params.append(uuid.UUID(cascade_uuid))
    rows = conn.execute(
        "SELECT uuid, content_hash, kind, node_path, child_level, revision_uuid, cascade_uuid "
        "FROM context_block WHERE "
        + " AND ".join(conditions)
        + " ORDER BY node_path, child_level, kind, created_at, uuid",
        tuple(params),
    ).fetchall()
    return [
        {
            "block_id": str(row[0]),
            "hash": row[1],
            "kind": row[2],
            "node_path": row[3],
            "child_level": row[4],
            "revision_uuid": str(row[5]) if row[5] else None,
            "cascade_uuid": str(row[6]) if row[6] else None,
        }
        for row in rows
    ]


def current_working_state(
    conn: psycopg.Connection,
    plan: Plan,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return the plan's current working revision and cascade identity (C-003).

    When the plan has an open cascade, the working state is the revision
    uuid the cascade's own ref currently points to, paired with the
    cascade's uuid. Otherwise the working state is the plan's head
    revision uuid, paired with None. This is the same (revision_uuid,
    cascade_uuid) pair resolve_context_revision produces when a context
    block is compiled, so a stored block matches this pair exactly when
    and only when it is current for the plan's live working state.
    """
    cascade = get_open_cascade(conn, plan.uuid)
    if cascade is not None:
        return get_ref(conn, plan.uuid, cascade.name), cascade.uuid
    return plan.head_revision_uuid, None


def has_current_common_block(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    node_path: str,
    child_level: int,
    working_revision: uuid.UUID | None,
    working_cascade: uuid.UUID | None,
) -> bool:
    """Return True iff a current common context block exists (C-002, C-003).

    A kind='common' context_block row for (node_path, child_level) counts
    as current only when its stored revision_uuid and cascade_uuid both
    match working_revision and working_cascade exactly, compared
    NULL-safely with IS NOT DISTINCT FROM. A block compiled against any
    other revision or cascade -- a stale block -- counts as absent.
    """
    row = conn.execute(
        "SELECT 1 FROM context_block WHERE plan_uuid = %s AND node_path = %s "
        "AND child_level = %s AND kind = 'common' "
        "AND revision_uuid IS NOT DISTINCT FROM %s AND cascade_uuid IS NOT DISTINCT FROM %s "
        "LIMIT 1",
        (plan_uuid, node_path, child_level, working_revision, working_cascade),
    ).fetchone()
    return row is not None
