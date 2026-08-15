"""Prompt-chain assembly view for scoped plan execution prompts.

The view is read-only. It compiles a gate-green plan scope into a
deduplicated, provider-neutral block corpus plus role-scoped assembly
instructions. Runtime retrieval, tokenization, padding, provider cache
markers, model selection, and execution dispatch are intentionally out
of scope here.

SPLIT (EIG block G). Scope normalization and structural selection --
PromptScope, normalize_scope/role/statuses, scope_atomic_steps,
eligible_atomic_steps, hrs_slice_for, branch_for_atomic -- live in the
sibling module :mod:`plan_manager.views.prompt_chain_scope`, moved there
verbatim to bring both files under the repository's ~400-line cap. They are
re-exported below, so every existing import of those names from THIS module
keeps working and this module stays the single public entry point.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

import psycopg

from plan_manager.domain.concept import Concept
from plan_manager.domain.concept_store import list_concepts
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.plan import get_plan
from plan_manager.domain.relation_store import list_relations
from plan_manager.domain.step import Step
from plan_manager.storage.canonical import canonical_json
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import (
    build_edges,
    load_steps,
    parent_path,
    topological_order,
    waves,
)
from plan_manager.views.prompt_assembly import step_content
from plan_manager.views.prompt_chain_scope import (  # re-exported, see module docstring
    DEFAULT_INCLUDE_STATUSES as DEFAULT_INCLUDE_STATUSES,
    PromptScope as PromptScope,
    ROLES as ROLES,
    branch_for_atomic as branch_for_atomic,
    eligible_atomic_steps as eligible_atomic_steps,
    hrs_slice_for as hrs_slice_for,
    normalize_role as normalize_role,
    normalize_scope as normalize_scope,
    normalize_statuses as normalize_statuses,
    scope_atomic_steps as scope_atomic_steps,
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


def _wave_data(
    atomic_steps: list[Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    nodes: dict[uuid.UUID, Step],
) -> tuple[list[list[str]], dict[uuid.UUID, int]]:
    """Partition the scoped atomic steps into execution waves.

    Bug 5d923c91: filtering ``edges`` to atomic-only endpoints before
    computing waves silently dropped every GS/TS-level depends_on edge
    (e.g. G-002 depends_on G-001), so an AS under a dependent GS could
    land in the same wave as, or before, an AS under the GS it structurally
    depends on. The fix reuses the exact closure algorithm graph_parallel_map
    drives (``waves`` in this module, over the FULL plan graph — every
    level, not atomic steps alone) instead of forking a second closure
    computation: ``waves`` already inherits an ancestor's explicit
    prerequisites down to every descendant and applies the strict-subtree-
    closure semantics from todo 19391f0b, so a GS/TS-level dependency edge
    reaches every atomic step in the dependent subtree even though the
    GS/TS nodes themselves never appear in the returned wave map.

    ``edges`` and ``nodes`` are the full plan edge/node sets (build_edges
    and load_steps over every node, every level) -- the same inputs
    graph_parallel_map's ``waves(nodes, edges)`` call uses, so the two
    commands always agree on relative order. The full-graph wave rows are
    then projected onto the scoped atomic subset: rows with no atomic step
    in scope are dropped and the remaining indices are compacted to a
    dense 0..N-1 range, so a narrow scope (e.g. one tactical step) still
    reports a compact wave map. On a genuine cycle the raised message
    carries the concrete canonical cycle path.
    """
    atomic_nodes = {step.uuid: step for step in atomic_steps}
    try:
        full_wave_rows = waves(nodes, edges, key_nodes=nodes)
    except ValueError as exc:
        if str(exc) == "cycle detected":
            _order, residual = topological_order(nodes, edges, key_nodes=nodes)
            cycle_path = " -> ".join(
                _step_key(nodes, nodes[node_uuid]) for node_uuid in residual
            )
            raise ValueError(f"cycle detected: {cycle_path}") from exc
        raise
    wave_index: dict[uuid.UUID, int] = {}
    result: list[list[str]] = []
    for row in full_wave_rows:
        scoped_row = [node_uuid for node_uuid in row if node_uuid in atomic_nodes]
        if not scoped_row:
            continue
        index = len(result)
        keys = [_step_key(nodes, atomic_nodes[node_uuid]) for node_uuid in scoped_row]
        result.append(keys)
        for node_uuid in scoped_row:
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

    edges = build_edges(nodes)
    dag_source = "execution: depends_on+file_priority"
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
