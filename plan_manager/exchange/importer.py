"""HRS text serialization: validation and ingestion of the human-authored Markdown source.

Realizes ExchangeFormat (C-021) together with the normative paragraph parsing (C-002).
Ingestion revision attribution follows VersionStore (C-018) directly, or CascadeChange
(C-016) when an open cascade is supplied. Import is the single path from files to the
source of truth; export never round-trips through import.
"""

import pathlib
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import yaml

from plan_manager.cascade.write import cascade_write
from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.concept import Concept
from plan_manager.domain.concept_store import insert_concept, list_concepts
from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.labeling import assign_missing_labels
from plan_manager.domain.paragraph import parse
from plan_manager.domain.paragraph_store import delete_paragraphs, insert_paragraphs
from plan_manager.domain.plan import create_plan, get_plan
from plan_manager.domain.project_binding import validate_plan_projects
from plan_manager.domain.relation import Relation
from plan_manager.domain.relation_store import insert_relation, list_relations
from plan_manager.exchange import canonical_form as cf
from plan_manager.exchange.layout_import import (
    import_steps,
    validate_as_file,
    validate_descriptor_dir,
)
from plan_manager.storage.errors import NotFoundError
from plan_manager.storage.identity import register_entity_identity, resolve_entity_identity
from plan_manager.storage.reference_catalog import resolve_entity_class
from plan_manager.storage.relation_index_store import replace_index
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


def _descriptor_project_ids(path: pathlib.Path) -> list[tuple[pathlib.Path, str]]:
    """Read optional project_id from one step descriptor."""
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or data.get("project_id") is None:
        return []
    return [(path, data["project_id"])]


def validate_hrs(text: str) -> list[str]:
    """Validate a candidate HRS Markdown document without touching the database.

    Parses `text` through the normative paragraph parsing (C-002) and reports
    structural and semantic issues that would block ingestion.

    :param text: The candidate HRS Markdown source document.
    :type text: str
    :return: A list of human-readable issue descriptions. An empty list means
        the document is ingestible.
    :rtype: list[str]
    """
    try:
        paragraphs = parse(text)
    except ValueError as exc:
        return [str(exc)]

    if not paragraphs:
        return ["document contains no binding paragraphs"]

    issues: list[str] = []
    seen_labels: set[str] = set()
    for paragraph in paragraphs:
        if paragraph.label is not None:
            if paragraph.label in seen_labels:
                issues.append(f"duplicate label: {paragraph.label}")
            else:
                seen_labels.add(paragraph.label)
    return issues


def import_hrs(conn, plan_uuid, text: str, author: str, cascade) -> dict:
    """Wholly replace a plan's stored paragraphs from an HRS Markdown document."""
    issues = validate_hrs(text)
    if issues:
        raise ValueError("; ".join(issues))

    paragraphs = parse(text)
    labeled, _new_labels = assign_missing_labels(paragraphs)

    delete_paragraphs(conn, plan_uuid)
    row_uuids = insert_paragraphs(conn, plan_uuid, labeled)

    snapshots = [
        {
            "kind": "paragraph",
            "uuid": str(row_uuid),
            "plan_uuid": str(plan_uuid),
            "label": paragraph.label,
            "text": paragraph.text,
            "position": paragraph.position,
        }
        for row_uuid, paragraph in zip(row_uuids, labeled)
    ]

    if cascade is None:
        plan = get_plan(conn, plan_uuid)
        record_revision(
            conn,
            plan_uuid,
            author,
            "hrs import",
            changes=list(zip(row_uuids, snapshots)),
            parent_revision_uuid=plan.head_revision_uuid,
            ref_name=None,
        )
    else:
        for row_uuid, snapshot in zip(row_uuids, snapshots):
            cascade_write(conn, plan_uuid, cascade, row_uuid, snapshot, [], author, "hrs import")

    return {
        "paragraphs": len(labeled),
        "written": [
            {
                "label": paragraph.label,
                "text": paragraph.text,
                "position": paragraph.position,
            }
            for paragraph in labeled
        ],
    }


def validate_layout(source_root) -> list[str]:
    """Validate a candidate standard-layout export tree without database access."""
    root = pathlib.Path(source_root)
    if not root.is_dir():
        return [f"source root not found: {source_root}"]

    issues: list[str] = []

    hrs_path = root / "source_spec.md"
    if not hrs_path.is_file():
        issues.append("missing source_spec.md")
        hrs_text = None
    else:
        hrs_text = hrs_path.read_text(encoding="utf-8")

    mrs_path = root / "spec.yaml"
    mrs_data = None
    skip_mrs_structure = False
    if not mrs_path.is_file():
        issues.append("missing spec.yaml")
        skip_mrs_structure = True
    else:
        try:
            mrs_data = yaml.safe_load(mrs_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            issues.append(f"spec.yaml: invalid YAML: {exc}")
            skip_mrs_structure = True
    if not skip_mrs_structure and (
        not isinstance(mrs_data, dict)
        or not isinstance(mrs_data.get("concepts"), list)
        or not isinstance(mrs_data.get("relations"), list)
    ):
        issues.append(
            "spec.yaml: must be a mapping with list-valued 'concepts' and "
            "'relations' keys"
        )
    if not skip_mrs_structure and isinstance(mrs_data, dict):
        project_ids = mrs_data.get("project_ids", [])
        primary_project_id = mrs_data.get("primary_project_id")
        if not isinstance(project_ids, list):
            issues.append("spec.yaml: project_ids must be a list when present")
        else:
            try:
                validate_plan_projects(project_ids, primary_project_id)
            except DomainCommandError as exc:
                issues.append(f"spec.yaml: {exc}")

    gs_dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("G-"))
    step_project_ids: list[tuple[Path, str]] = []
    for gs_dir in gs_dirs:
        issues.extend(validate_descriptor_dir(gs_dir, "G"))
        step_project_ids.extend(_descriptor_project_ids(gs_dir / "README.yaml"))
        ts_dirs = sorted(
            p for p in gs_dir.iterdir() if p.is_dir() and p.name.startswith("T-")
        )
        for ts_dir in ts_dirs:
            issues.extend(validate_descriptor_dir(ts_dir, "T"))
            step_project_ids.extend(_descriptor_project_ids(ts_dir / "README.yaml"))
            as_dir = ts_dir / "atomic_steps"
            if as_dir.is_dir():
                for as_file in sorted(as_dir.glob("*.yaml")):
                    issues.extend(validate_as_file(as_file))
                    step_project_ids.extend(_descriptor_project_ids(as_file))

    if not skip_mrs_structure and isinstance(mrs_data, dict):
        bound_project_ids = set(mrs_data.get("project_ids", []))
        for path, project_id in step_project_ids:
            if project_id not in bound_project_ids:
                issues.append(
                    f"{path}: project_id {project_id!r} is not present in spec.yaml project_ids"
                )

    if hrs_text is not None:
        issues.extend(f"hrs: {issue}" for issue in validate_hrs(hrs_text))

    return issues


def import_plan(conn, source_root, author: str):
    """Ingest a validated standard-layout export tree into a new plan."""
    issues = validate_layout(source_root)
    if issues:
        raise ValueError("; ".join(issues))

    root = pathlib.Path(source_root)
    plan = create_plan(conn, name=root.name)

    hrs_text = (root / "source_spec.md").read_text(encoding="utf-8")
    import_hrs(conn, plan.uuid, hrs_text, author, None)

    mrs_data = yaml.safe_load((root / "spec.yaml").read_text(encoding="utf-8"))
    project_ids = list(mrs_data.get("project_ids", []))
    primary_project_id = mrs_data.get("primary_project_id")
    validate_plan_projects(project_ids, primary_project_id)
    conn.execute(
        "UPDATE plan SET project_ids = %s, primary_project_id = %s WHERE uuid = %s",
        (project_ids, primary_project_id, plan.uuid),
    )
    changes: list[tuple] = []

    for entry in mrs_data["concepts"]:
        concept = Concept(
            concept_id=entry["concept_id"],
            name=entry["name"],
            definition=entry["definition"],
            properties=list(entry.get("properties", [])),
            source_labels=list(entry.get("source_labels", [])),
        )
        concept_uuid = insert_concept(conn, plan.uuid, concept)
        changes.append(
            (
                concept_uuid,
                {
                    "kind": "concept",
                    "uuid": str(concept_uuid),
                    "plan_uuid": str(plan.uuid),
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "definition": concept.definition,
                    "properties": concept.properties,
                    "source_labels": concept.source_labels,
                },
            )
        )

    for entry in mrs_data["relations"]:
        relation = Relation(
            from_concept=entry["from_concept"],
            to_concept=entry["to_concept"],
            type=entry["type"],
        )
        relation_uuid = insert_relation(conn, plan.uuid, relation)
        changes.append(
            (
                relation_uuid,
                {
                    "kind": "relation",
                    "uuid": str(relation_uuid),
                    "plan_uuid": str(plan.uuid),
                    "from_concept": relation.from_concept,
                    "to_concept": relation.to_concept,
                    "type": relation.type,
                },
            )
        )

    step_changes = import_steps(conn, plan.uuid, root)
    changes.extend(step_changes)

    record_revision(
        conn,
        plan.uuid,
        author,
        "plan import",
        changes=changes,
        parent_revision_uuid=get_plan(conn, plan.uuid).head_revision_uuid,
        ref_name=None,
    )

    stored_concepts = list_concepts(conn, plan.uuid)
    if len(stored_concepts) != len(mrs_data["concepts"]):
        raise ValueError(
            "concept count mismatch on import: expected "
            f"{len(mrs_data['concepts'])} got {len(stored_concepts)}"
        )
    stored_relations = list_relations(conn, plan.uuid)
    if len(stored_relations) != len(mrs_data["relations"]):
        raise ValueError(
            "relation count mismatch on import: expected "
            f"{len(mrs_data['relations'])} got {len(stored_relations)}"
        )
    stored_steps = load_steps(conn, plan.uuid)
    if len(stored_steps) != len(step_changes):
        raise ValueError(
            f"step count mismatch on import: expected {len(step_changes)} "
            f"got {len(stored_steps)}"
        )

    return plan.uuid


# CR-7 G-005/T-001/A-002: canonical-form import with identity preservation.
_CANONICAL_IMPORT_SEATS: dict[type, type] = {}
_SEAT_COPIED_ATTRS = ("TABLE_NAME", "COLUMNS", "SOFT_DELETE_COLUMN", "CREATED_AT_COLUMN", "UPDATED_AT_COLUMN", "OWNER_COLUMN", "OWNER_ROOT", "OWNER_GAP")


def _canonical_import_seat(entity_cls: type) -> type:
    """Cached ref-addressable seat (mirrors cascade/restore.py's _RestoreSeat): ID_COLUMN is the ref, not a composite business key."""
    if entity_cls in _CANONICAL_IMPORT_SEATS:
        return _CANONICAL_IMPORT_SEATS[entity_cls]
    namespace = {attr: getattr(entity_cls, attr) for attr in _SEAT_COPIED_ATTRS}
    namespace.update(ENTITY_TYPE=None, ID_COLUMN=cf._entity_ref_column(entity_cls), ID_COLUMNS=(),
                      INSERT_COLUMNS=(), UPDATE_COLUMNS=(), REGISTER_IDENTITY=False, ENGINE_MANAGED_TIMESTAMPS=False)
    seat = type(f"_CanonicalImportSeat_{entity_cls.__name__}", (DataclassEntity,), namespace)
    _CANONICAL_IMPORT_SEATS[entity_cls] = seat
    return seat

def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(value)

def _identity_state(conn, entity_cls: type, seat: type, ref: uuid.UUID, entity_kind: str) -> str:
    """"absent"/"same_kind"/"cross_kind": registry-tracked via resolve_entity_identity, else row-level via the seat (e.g. step_runtime)."""
    if entity_cls.REGISTER_IDENTITY:
        try:
            existing = resolve_entity_identity(conn, ref)
        except NotFoundError:
            return "absent"
        return "same_kind" if existing["entity_type"] == entity_kind else "cross_kind"
    return "same_kind" if seat.crud_get(conn, ref) is not None else "absent"

def _canonical_row_values(entity_cls: type, record: Mapping[str, Any]) -> dict[str, Any]:
    """Rehydrate one JSON-safe canonical record into typed column values; properties pass opaque."""
    ref_column = cf._entity_ref_column(entity_cls)
    values: dict[str, Any] = dict(record.get("properties") or {})
    values[ref_column] = record["ref"]
    if entity_cls.OWNER_COLUMN is not None:
        owner = record["owner"]
        values[entity_cls.OWNER_COLUMN] = uuid.UUID(owner) if isinstance(owner, str) else owner
    if entity_cls.SOFT_DELETE_COLUMN is not None:
        # markdel's original deletion instant is unrecoverable by design (canonical_form's own
        # documented loss); marked -> a fresh stamp, unmarked -> NULL.
        values[entity_cls.SOFT_DELETE_COLUMN] = datetime.now(timezone.utc) if record["markdel"] else None
    for column, key in ((entity_cls.CREATED_AT_COLUMN, "created_at"), (entity_cls.UPDATED_AT_COLUMN, "updated_at")):
        if column is not None:
            value = record[key]
            values[column] = datetime.fromisoformat(value) if isinstance(value, str) else value
    return values


def import_canonical_document(conn, document: Mapping[str, Any]) -> dict:
    """Import a canonical-form document with identity preservation, as one schema-and-data transfer
    inside the caller's own transaction (never committed here: any exception rolls back everything
    written). ABSENT ref: recovery/import admission, ref+timestamps preserved. SAME-kind ref: cleared
    and replaced via one crud_update. ANOTHER-kind ref: aborts immediately. Checksum precedes any
    write. Relations are written last via relation_index_store.replace_index."""
    if not cf.verify_document(document):
        raise ValueError("canonical document checksum verification failed; refusing to write")
    created = replaced = 0
    for record in document.get("entities", ()):
        entity_kind = record["entity_kind"]
        entity_cls = resolve_entity_class(entity_kind)
        seat = _canonical_import_seat(entity_cls)
        ref = _as_uuid(record["ref"])
        state = _identity_state(conn, entity_cls, seat, ref, entity_kind)
        if state == "cross_kind":
            raise ValueError(f"identity conflict on import: ref {ref} is already registered under a "
                              f"different entity kind than {entity_kind!r}; aborting the import")
        values = _canonical_row_values(entity_cls, record)
        if state == "absent":
            seat.crud_create(conn, values, returning=False, recovery_mode=True, admit_original_timestamps=True)
            if entity_cls.REGISTER_IDENTITY:
                register_entity_identity(conn, entity_id=ref, table_name=entity_cls.TABLE_NAME,
                                          entity_type=entity_kind, created_at=values.get(entity_cls.CREATED_AT_COLUMN))
            created += 1
        else:  # same_kind: clear and replace every non-identity column.
            update_values = {c: v for c, v in values.items() if c != seat.ID_COLUMN}
            seat.crud_update(conn, ref, update_values, returning=False)
            replaced += 1
    triples = [(_as_uuid(t["source_ref"]), _as_uuid(t["target_ref"]), _as_uuid(t["field_ref"]))
               for t in document.get("relations", ())]
    written = replace_index(conn, triples)
    return {"entities_created": created, "entities_replaced": replaced, "relations_written": written}
