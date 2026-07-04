"""HRS text serialization: validation and ingestion of the human-authored Markdown source.

Realizes ExchangeFormat (C-021) together with the normative paragraph parsing (C-002).
Ingestion revision attribution follows VersionStore (C-018) directly, or CascadeChange
(C-016) when an open cascade is supplied. Import is the single path from files to the
source of truth; export never round-trips through import.
"""

import pathlib

import yaml

from plan_manager.cascade.write import cascade_write
from plan_manager.domain.concept import Concept
from plan_manager.domain.concept_store import insert_concept, list_concepts
from plan_manager.domain.labeling import assign_missing_labels
from plan_manager.domain.paragraph import parse
from plan_manager.domain.paragraph_store import delete_paragraphs, insert_paragraphs
from plan_manager.domain.plan import create_plan, get_plan
from plan_manager.domain.relation import Relation
from plan_manager.domain.relation_store import insert_relation, list_relations
from plan_manager.exchange.layout_import import (
    import_steps,
    validate_as_file,
    validate_descriptor_dir,
)
from plan_manager.storage.version_store import record_revision
from plan_manager.views.dependency_graph import load_steps


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

    return {"paragraphs": len(labeled)}


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

    gs_dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.startswith("G-"))
    for gs_dir in gs_dirs:
        issues.extend(validate_descriptor_dir(gs_dir, "G"))
        ts_dirs = sorted(
            p for p in gs_dir.iterdir() if p.is_dir() and p.name.startswith("T-")
        )
        for ts_dir in ts_dirs:
            issues.extend(validate_descriptor_dir(ts_dir, "T"))
            as_dir = ts_dir / "atomic_steps"
            if as_dir.is_dir():
                for as_file in sorted(as_dir.glob("*.yaml")):
                    issues.extend(validate_as_file(as_file))

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
