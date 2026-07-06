"""Export a stored plan into the standard exchange layout."""

from pathlib import Path
import uuid

import yaml

from plan_manager.domain.concept_store import list_concepts
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.plan import get_plan
from plan_manager.domain.relation_store import list_relations
from plan_manager.cascade.record import get_open_cascade
from plan_manager.storage.version_store import get_ref
from plan_manager.storage.version_ops import checkout_read, state_at
from plan_manager.views.dependency_graph import load_steps


class ExportError(RuntimeError):
    """Raised when an export cannot be represented as a standard layout."""


HRS_FILENAME = "source_spec.md"
MRS_FILENAME = "spec.yaml"
STEP_README = "README.yaml"
ATOMIC_DIR = "atomic_steps"


def _plain(value):
    """Convert UUID-bearing snapshots into safe YAML-compatible values."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def export_hrs(conn, plan_uuid) -> str:
    """Render the plan's stored HRS paragraphs as Markdown text."""
    rows = list_paragraphs(conn, plan_uuid)
    return "\n\n".join("{" + row.label + "} " + row.text for row in rows) + "\n"


def emit_yaml(path, data: dict) -> None:
    """Safely write one YAML mapping and verify it round-trips."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _plain(data)
    text = yaml.safe_dump(
        data, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    loaded = yaml.safe_load(text)
    if loaded != data:
        raise ExportError(f"round-trip failed: {path}")
    path.write_text(text, encoding="utf-8")


def _step_to_dict(step) -> dict:
    return {
        "uuid": str(step.uuid),
        "plan_uuid": str(step.plan_uuid),
        "parent_step_uuid": str(step.parent_step_uuid)
        if step.parent_step_uuid is not None
        else None,
        "level": step.level,
        "step_id": step.step_id,
        "slug": step.slug,
        "fields": step.fields,
        "depends_on": step.depends_on,
        "concepts": step.concepts,
        "project_id": step.project_id,
        "status": step.status,
    }


def assemble_state(conn, plan_uuid, revision_uuid) -> dict:
    """Assemble current or historical plan state into export dictionaries."""
    if revision_uuid is None:
        steps = [_step_to_dict(step) for step in load_steps(conn, plan_uuid).values()]
        concepts = [
            {
                "concept_id": c.concept_id,
                "name": c.name,
                "definition": c.definition,
                "properties": c.properties,
                "source_labels": c.source_labels,
            }
            for c in list_concepts(conn, plan_uuid)
        ]
        relations = [
            {"from_concept": f, "to_concept": t, "type": rel_type}
            for f, t, rel_type in list_relations(conn, plan_uuid)
        ]
        paragraphs = [
            {
                "uuid": str(p.uuid),
                "plan_uuid": str(p.plan_uuid),
                "label": p.label,
                "text": p.text,
                "position": p.position,
            }
            for p in list_paragraphs(conn, plan_uuid)
        ]
        state = {
            "steps": steps,
            "concepts": concepts,
            "relations": relations,
            "paragraphs": paragraphs,
        }
        state["steps"].sort(key=lambda item: (item["level"], item["step_id"]))
        state["concepts"].sort(key=lambda item: item["concept_id"])
        state["relations"].sort(
            key=lambda item: (item["from_concept"], item["to_concept"], item["type"])
        )
        state["paragraphs"].sort(key=lambda item: item["position"])
        return state

    node_map = state_at(conn, plan_uuid, revision_uuid)
    state = {"steps": [], "concepts": [], "relations": [], "paragraphs": []}
    for node_uuid in node_map:
        snap = checkout_read(conn, plan_uuid, revision_uuid, node_uuid)
        if snap.get("deleted"):
            continue
        snap = _plain(snap)
        kind = snap.get("kind")
        body = {key: value for key, value in snap.items() if key != "kind"}
        if kind == "step":
            state["steps"].append(body)
        elif kind == "concept":
            state["concepts"].append(body)
        elif kind == "relation":
            state["relations"].append(body)
        elif kind == "paragraph":
            state["paragraphs"].append(body)
    state["steps"].sort(key=lambda item: (item["level"], item["step_id"]))
    state["concepts"].sort(key=lambda item: item["concept_id"])
    state["relations"].sort(
        key=lambda item: (item["from_concept"], item["to_concept"], item["type"])
    )
    state["paragraphs"] = _dedupe_paragraphs_by_label(state["paragraphs"])
    state["paragraphs"].sort(key=lambda item: item["position"])
    return state


def render_hrs_text(paragraphs: list[dict]) -> str:
    """Render paragraph dictionaries into HRS Markdown text."""
    ordered = sorted(paragraphs, key=lambda p: p["position"])
    return "\n\n".join(
        "{" + p["label"] + "} " + _paragraph_text_without_label(p)
        for p in ordered
    ) + "\n"


def _paragraph_text_without_label(paragraph: dict) -> str:
    """Return paragraph text without a leading rendered label prefix."""
    text = paragraph["text"]
    prefix = "{" + paragraph["label"] + "} "
    if isinstance(text, str) and text.startswith(prefix):
        return text[len(prefix):]
    return text


def _dedupe_paragraphs_by_label(paragraphs: list[dict]) -> list[dict]:
    """Keep the first paragraph snapshot for each label."""
    seen: set[str] = set()
    result: list[dict] = []
    for paragraph in paragraphs:
        label = paragraph["label"]
        if label in seen:
            continue
        seen.add(label)
        result.append(paragraph)
    return result


def step_descriptor(step: dict) -> dict:
    """Build the YAML descriptor for one step dictionary."""
    descriptor = {"step_id": step["step_id"]}
    descriptor.update(step.get("fields", {}))
    if step.get("depends_on"):
        descriptor["depends_on"] = step["depends_on"]
    if step.get("concepts"):
        descriptor["concepts"] = step["concepts"]
    descriptor["project_id"] = step.get("project_id")
    descriptor["status"] = step["status"]
    return descriptor


def export_plan(conn, plan_uuid, export_root, revision_uuid=None) -> dict:
    """Export a plan to the standard directory layout."""
    plan = get_plan(conn, plan_uuid)
    root = Path(export_root) / plan.name
    state = assemble_state(conn, plan_uuid, revision_uuid)
    root.mkdir(parents=True, exist_ok=True)
    (root / HRS_FILENAME).write_text(
        render_hrs_text(state["paragraphs"]), encoding="utf-8"
    )
    files = 1
    mrs_concepts = [
        {
            "concept_id": concept["concept_id"],
            "name": concept["name"],
            "definition": concept["definition"],
            "properties": concept["properties"],
            "source_labels": concept["source_labels"],
        }
        for concept in state["concepts"]
    ]
    mrs_relations = [
        {
            "from_concept": relation["from_concept"],
            "to_concept": relation["to_concept"],
            "type": relation["type"],
        }
        for relation in state["relations"]
    ]
    emit_yaml(
        root / MRS_FILENAME,
        {
            "project_ids": plan.project_ids,
            "primary_project_id": plan.primary_project_id,
            "concepts": mrs_concepts,
            "relations": mrs_relations,
        },
    )
    files += 1

    steps = sorted(state["steps"], key=lambda s: (s["level"], s["step_id"]))
    by_uuid = {str(s["uuid"]): s for s in steps}
    paths = {}
    for step in steps:
        if step["level"] == 3:
            path = root / f"{step['step_id']}-{step['slug']}"
            emit_yaml(path / STEP_README, step_descriptor(step))
            files += 1
            paths[str(step["uuid"])] = path
        elif step["level"] == 4:
            parent = paths.get(str(step["parent_step_uuid"]))
            if parent is None:
                raise ExportError(f"missing parent for step {step['step_id']}")
            path = parent / f"{step['step_id']}-{step['slug']}"
            emit_yaml(path / STEP_README, step_descriptor(step))
            files += 1
            paths[str(step["uuid"])] = path
        elif step["level"] == 5:
            parent = by_uuid.get(str(step["parent_step_uuid"]))
            parent_path = paths.get(str(step["parent_step_uuid"]))
            if parent is None or parent_path is None:
                raise ExportError(f"missing parent for step {step['step_id']}")
            emit_yaml(
                parent_path / ATOMIC_DIR / f"{step['step_id']}-{step['slug']}.yaml",
                step_descriptor(step),
            )
            files += 1

    return {"root": str(root), "files": files}


def export_working_snapshot(conn, plan_uuid, export_root) -> dict:
    """Export the effective live working state to the standard layout.

    If a cascade is open, the cascade ref's tip revision is exported. If no
    cascade is open, this preserves the existing head export behavior by
    delegating to export_plan without an explicit revision.
    """
    plan = get_plan(conn, plan_uuid)
    cascade = get_open_cascade(conn, plan_uuid)
    if cascade is None:
        summary = export_plan(conn, plan_uuid, export_root)
        return {
            **summary,
            "based_on_revision": (
                str(plan.head_revision_uuid) if plan.head_revision_uuid is not None else None
            ),
            "cascade_uuid": None,
            "snapshot_revision": (
                str(plan.head_revision_uuid) if plan.head_revision_uuid is not None else None
            ),
        }

    tip = get_ref(conn, plan_uuid, cascade.name)
    summary = export_plan(conn, plan_uuid, export_root, revision_uuid=tip)
    return {
        **summary,
        "based_on_revision": (
            str(cascade.base_revision_uuid)
            if cascade.base_revision_uuid is not None
            else None
        ),
        "cascade_uuid": str(cascade.uuid),
        "snapshot_revision": str(tip),
    }
