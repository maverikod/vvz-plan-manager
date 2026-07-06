"""Prompt-chain assembly view for scoped plan execution prompts.

The view is read-only. It compiles a gate-green plan scope into a
deduplicated, provider-neutral block corpus plus role-scoped assembly
instructions. Runtime retrieval, tokenization, padding, provider cache
markers, model selection, and execution dispatch are intentionally out
of scope here.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from plan_manager.domain.concept import Concept
from plan_manager.domain.concept_store import list_concepts
from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.plan import get_plan
from plan_manager.domain.relation_store import list_relations
from plan_manager.domain.status_model import STATUSES
from plan_manager.domain.step import Step
from plan_manager.storage.canonical import canonical_json
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import load_steps, parent_path, waves
from plan_manager.views.prompt_assembly import step_content


DEFAULT_INCLUDE_STATUSES = ("frozen", "ready_for_review")
ROLES = ("coder", "review", "conscience")

_GLOBAL_SCOPE_RE = re.compile(r"^G-\d{3}$")
_TACTICAL_SCOPE_RE = re.compile(r"^(G-\d{3})/(T-\d{3})$")
_DEPENDENCY_RELATION_TYPES = {"depends_on", "consumes", "uses"}


@dataclass(frozen=True)
class PromptScope:
    """Resolved prompt-chain scope."""

    label: str
    gs_step_id: str | None
    ts_step_id: str | None


def normalize_scope(scope: str | None) -> PromptScope:
    """Normalize and validate a prompt-chain scope string."""
    if scope is None or scope == "" or scope == "whole_plan":
        return PromptScope("whole_plan", None, None)
    if _GLOBAL_SCOPE_RE.match(scope):
        return PromptScope(scope, scope, None)
    tactical = _TACTICAL_SCOPE_RE.match(scope)
    if tactical is not None:
        return PromptScope(scope, tactical.group(1), tactical.group(2))
    raise ValueError(
        "scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'"
    )


def normalize_role(role: str | None) -> str:
    """Normalize the role selector used by assembly manifests."""
    value = "coder" if role is None or role == "" else role
    if value not in ROLES:
        raise ValueError(f"role must be one of {list(ROLES)}")
    return value


def normalize_statuses(include_statuses: list[str] | None) -> list[str]:
    """Normalize the status filter used to select eligible branches."""
    values = list(DEFAULT_INCLUDE_STATUSES) if include_statuses is None else include_statuses
    if not values:
        raise ValueError("include_statuses must not be empty")
    allowed = set(STATUSES)
    unknown = sorted({status for status in values if status not in allowed})
    if unknown:
        raise ValueError(f"unknown status in include_statuses: {unknown}")
    return sorted(set(values))


def scope_atomic_steps(
    nodes: dict[uuid.UUID, Step],
    scope: PromptScope,
) -> list[Step]:
    """Return all atomic steps structurally contained in ``scope``."""
    if scope.gs_step_id is not None and not any(
        step.level == 3 and step.step_id == scope.gs_step_id for step in nodes.values()
    ):
        raise ValueError(f"no global step found for scope {scope.gs_step_id!r}")
    if scope.ts_step_id is not None and not any(
        step.level == 4
        and step.step_id == scope.ts_step_id
        and parent_path(nodes, step) == scope.gs_step_id
        for step in nodes.values()
    ):
        raise ValueError(f"no tactical step found for scope {scope.label!r}")

    result = []
    for step in nodes.values():
        if step.level != 5:
            continue
        branch_path = parent_path(nodes, step)
        if scope.gs_step_id is not None and not branch_path.startswith(
            scope.gs_step_id + "/"
        ):
            continue
        if scope.ts_step_id is not None and branch_path != scope.label:
            continue
        result.append(step)
    result.sort(
        key=lambda step: (
            parent_path(nodes, step),
            step.fields.get("priority", 0),
            step.step_id,
        )
    )
    return result


def _ancestor_chain(nodes: dict[uuid.UUID, Step], atomic: Step) -> tuple[Step, Step, Step]:
    ts = nodes[atomic.parent_step_uuid]
    gs = nodes[ts.parent_step_uuid]
    return gs, ts, atomic


def eligible_atomic_steps(
    nodes: dict[uuid.UUID, Step],
    atomic_steps: list[Step],
    include_statuses: list[str],
) -> list[Step]:
    """Filter atomic steps whose GS, TS, and AS statuses are included."""
    allowed = set(include_statuses)
    eligible = []
    for atomic in atomic_steps:
        gs, ts, current = _ancestor_chain(nodes, atomic)
        if gs.status in allowed and ts.status in allowed and current.status in allowed:
            eligible.append(atomic)
    return eligible


def hrs_slice_for(
    paragraphs: list[Paragraph],
    gs: Step,
) -> list[Paragraph]:
    """Return the HRS paragraphs referenced by a global step."""
    bare = {
        label[1:-1] if label.startswith("{") and label.endswith("}") else label
        for label in gs.fields.get("source_labels", [])
    }
    return [
        paragraph
        for paragraph in paragraphs
        if paragraph.label is not None and paragraph.label in bare
    ]


def branch_for_atomic(
    nodes: dict[uuid.UUID, Step],
    paragraphs: list[Paragraph],
    plan_uuid: uuid.UUID,
    atomic: Step,
) -> Branch:
    """Construct an in-memory Branch view for one atomic step."""
    gs, ts, current = _ancestor_chain(nodes, atomic)
    return Branch(
        plan_uuid=plan_uuid,
        gs=gs,
        ts=ts,
        atomic=current,
        hrs_slice=hrs_slice_for(paragraphs, gs),
    )


def cache_key(value: Any) -> str:
    """Return the stable cache key for one canonical block value."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _block(content: Any) -> dict[str, Any]:
    return {"content": content, "cache_key": cache_key(content)}


def _concept_content(concept: Concept) -> dict[str, Any]:
    return {
        "concept_id": concept.concept_id,
        "name": concept.name,
        "definition": concept.definition,
        "properties": list(concept.properties),
        "source_labels": list(concept.source_labels),
    }


def _relation_key(from_concept: str, to_concept: str, relation_type: str) -> str:
    return f"{from_concept}|{relation_type}|{to_concept}"


def _step_key(nodes: dict[uuid.UUID, Step], atomic: Step) -> str:
    return f"{parent_path(nodes, atomic)}/{atomic.step_id}"


def _atomic_content(atomic: Step) -> dict[str, Any]:
    return {
        "prompt": atomic.fields.get("prompt", ""),
        "operation": atomic.fields.get("operation"),
        "target_file": atomic.fields.get("target_file"),
        "verification": atomic.fields.get("verification", {}),
        "priority": atomic.fields.get("priority"),
        "concepts": list(atomic.concepts),
        "depends_on": list(atomic.depends_on),
        "project_id": atomic.project_id,
        "status": atomic.status,
    }


def _tool_instructions(role: str) -> dict[str, Any]:
    if role == "coder":
        content = (
            "Use tool access to inspect and edit files. Execute only the AS block "
            "plus these tool instructions. If the AS names a file or exemplar, read "
            "that path directly with tools. Do not perform retrieval or semantic "
            "search, and do not assume HRS/MRS/GS/TS context is present."
        )
    elif role == "review":
        content = (
            "Review the AS against the selected upper-layer blocks and reported "
            "verification. Do not mutate project files while reviewing."
        )
    else:
        content = (
            "Judge whether the AS preserves the plan intent represented by the "
            "selected upper-layer blocks. Do not mutate project files."
        )
    return {"content": content, "cache_key": cache_key(content)}


def _module_token(path: str) -> str:
    if path.endswith(".py"):
        return path[:-3].replace("/", ".")
    return path


def _step_mentions_target(consumer: Step, producer_target: str) -> bool:
    prompt = str(consumer.fields.get("prompt", ""))
    return producer_target in prompt or _module_token(producer_target) in prompt


def _derived_edges(
    atomic_steps: list[Step],
    relations: list[tuple[str, str, str]],
) -> tuple[set[tuple[uuid.UUID, uuid.UUID]], str]:
    """Derive atomic-step DAG edges for prompt-chain waves."""
    by_concept: dict[str, list[Step]] = {}
    for step in atomic_steps:
        for concept_id in step.concepts:
            by_concept.setdefault(concept_id, []).append(step)

    edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    for from_concept, to_concept, relation_type in relations:
        if relation_type not in _DEPENDENCY_RELATION_TYPES:
            continue
        for consumer in by_concept.get(from_concept, []):
            for producer in by_concept.get(to_concept, []):
                if consumer.uuid != producer.uuid:
                    edges.add((producer.uuid, consumer.uuid))

    producers = [
        step
        for step in atomic_steps
        if step.fields.get("operation") in {"create_file", "rename_file"}
        and step.fields.get("target_file")
    ]
    for producer in producers:
        target = str(producer.fields["target_file"])
        for consumer in atomic_steps:
            if consumer.uuid != producer.uuid and _step_mentions_target(consumer, target):
                edges.add((producer.uuid, consumer.uuid))

    explicit_added = False
    by_sibling_key = {
        (step.parent_step_uuid, step.step_id): step for step in atomic_steps
    }
    for dependent in atomic_steps:
        for dep_step_id in dependent.depends_on:
            prerequisite = by_sibling_key.get((dependent.parent_step_uuid, dep_step_id))
            if prerequisite is not None:
                edges.add((prerequisite.uuid, dependent.uuid))
                explicit_added = True

    if explicit_added and len(edges) > 0:
        return edges, "mixed"
    return edges, "derived: relations+target_file"


def _wave_data(
    atomic_steps: list[Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    nodes: dict[uuid.UUID, Step],
) -> tuple[list[list[str]], dict[uuid.UUID, int]]:
    atomic_nodes = {step.uuid: step for step in atomic_steps}
    atomic_edges = {
        (prereq, dependent)
        for prereq, dependent in edges
        if prereq in atomic_nodes and dependent in atomic_nodes
    }
    wave_rows = waves(atomic_nodes, atomic_edges)
    wave_index: dict[uuid.UUID, int] = {}
    result: list[list[str]] = []
    for index, row in enumerate(wave_rows):
        keys = [_step_key(nodes, atomic_nodes[node_uuid]) for node_uuid in row]
        result.append(keys)
        for node_uuid in row:
            wave_index[node_uuid] = index
    return result, wave_index


def _assembly_use(role: str, step_key: str, branch: Branch) -> dict[str, str]:
    if role == "coder":
        return {"as": step_key, "tool_instructions": role}
    return {
        "hrs": branch.gs.step_id,
        "mrs": ",".join(sorted(branch.atomic.concepts)),
        "gs": branch.gs.step_id,
        "ts": f"{branch.gs.step_id}/{branch.ts.step_id}",
        "as": step_key,
        "tool_instructions": role,
    }


def assemble_prompt_chain(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    plan_name: str,
    revision_uuid: uuid.UUID | None,
    scope: PromptScope,
    include_statuses: list[str],
    role: str = "coder",
) -> dict[str, Any]:
    """Assemble the prompt-chain payload for a gate-green scope."""
    role = normalize_role(role)
    nodes = load_steps(conn, plan_uuid)
    paragraphs = list_paragraphs(conn, plan_uuid)
    concepts = {concept.concept_id: concept for concept in list_concepts(conn, plan_uuid)}
    relations = list_relations(conn, plan_uuid)
    atomic_steps = eligible_atomic_steps(
        nodes,
        scope_atomic_steps(nodes, scope),
        include_statuses,
    )

    edges, dag_source = _derived_edges(atomic_steps, relations)
    wave_rows, wave_index = _wave_data(atomic_steps, edges, nodes)

    blocks: dict[str, dict[str, dict[str, Any]]] = {
        "hrs": {},
        "mrs": {},
        "gs": {},
        "ts": {},
        "as": {},
        "tool_instructions": {role: _tool_instructions(role)},
    }
    assembly: list[dict[str, Any]] = []

    for atomic in atomic_steps:
        branch = branch_for_atomic(nodes, paragraphs, plan_uuid, atomic)
        step_key = _step_key(nodes, atomic)
        branch_path = parent_path(nodes, atomic)

        for paragraph in branch.hrs_slice:
            if paragraph.label is not None:
                content = "{" + paragraph.label + "} " + paragraph.text
                blocks["hrs"].setdefault("{" + paragraph.label + "}", _block(content))

        for concept_id in sorted(branch.atomic.concepts):
            concept = concepts.get(concept_id)
            if concept is not None:
                blocks["mrs"].setdefault(concept_id, _block(_concept_content(concept)))

        for from_concept, to_concept, relation_type in relations:
            if from_concept in branch.atomic.concepts and to_concept in branch.atomic.concepts:
                key = _relation_key(from_concept, to_concept, relation_type)
                blocks["mrs"].setdefault(
                    key,
                    _block(
                        {
                            "from_concept": from_concept,
                            "to_concept": to_concept,
                            "type": relation_type,
                        }
                    ),
                )

        gs_content = step_content(branch.gs)
        blocks["gs"].setdefault(branch.gs.step_id, _block(gs_content))

        ts_key = f"{branch.gs.step_id}/{branch.ts.step_id}"
        ts_content = step_content(branch.ts)
        blocks["ts"].setdefault(ts_key, _block(ts_content))

        blocks["as"].setdefault(step_key, _block(_atomic_content(atomic)))

        assembly.append(
            {
                "step": step_key,
                "wave": wave_index[atomic.uuid],
                "branch_path": branch_path,
                "priority": atomic.fields["priority"],
                "role": role,
                "use": _assembly_use(role, step_key, branch),
            }
        )

    assembly.sort(
        key=lambda row: (
            row["branch_path"],
            row["priority"],
            row["step"],
        )
    )

    plan = get_plan(conn, plan_uuid)
    counts = {level: len(values) for level, values in blocks.items()}
    counts["assembly"] = len(assembly)
    return {
        "plan": plan_name,
        "revision": str(revision_uuid) if revision_uuid is not None else None,
        "scope": scope.label,
        "role": role,
        "waves": wave_rows,
        "blocks": blocks,
        "assembly": assembly,
        "meta": {
            "dag_source": dag_source,
            "counts": counts,
            "include_statuses": include_statuses,
            "projects": {
                "project_ids": plan.project_ids,
                "primary_project_id": plan.primary_project_id,
            },
        },
    }
