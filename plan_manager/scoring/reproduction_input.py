"""Assemble a plan's ScopedNode tree and embed_fn for SemanticReproductionTree
(C-001) computation (build_tree, plan_manager.scoring.reproduction_tree).

Loads a plan's current step tree, builds each node's own reconstructed or
semantic summary text (ReconstructedSummary / SemanticSummary, C-004 / C-003)
and expected-scope text (ExpectedScope, C-005) on the scope-aware coverage
foundation (ScopeAwareCoverageFoundation, C-002) via
plan_manager.scoring.reproduction_scope, and assembles the resulting
hierarchy into one root ScopedNode ready for
plan_manager.scoring.reproduction_tree.build_tree, together with a real
embed_fn resolving text to an embedding vector through the existing
embedding client.
"""

from __future__ import annotations

import uuid
from typing import Callable

import psycopg

from plan_manager.domain.concept import Concept
from plan_manager.domain.concept_store import list_concepts
from plan_manager.domain.relation_store import list_relations
from plan_manager.domain.step import Step
from plan_manager.scoring.embedding import embed_text
from plan_manager.scoring.estimators import load_concept_rows
from plan_manager.scoring.reproduction_scope import (
    aggregated_scope,
    expected_scope_text,
    leaf_scope,
    paragraph_text_by_label,
)
from plan_manager.scoring.reproduction_tree import ScopedNode
from plan_manager.views.atomic_summary import build_atomic_semantic_summary
from plan_manager.views.branch import resolve_branch
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.expected_scope import build_expected_scope
from plan_manager.views.reconstruct_global_summary import reconstruct_global_summary
from plan_manager.views.reconstruct_plan_summary import reconstruct_plan_summary
from plan_manager.views.reconstruct_tactical_summary import reconstruct_tactical_summary


ROOT_PATH = "PLAN"


def _children(
    steps_by_uuid: dict[uuid.UUID, Step], parent_uuid: uuid.UUID, level: int
) -> list[Step]:
    """List parent_uuid's direct children of the given level, step_id-sorted."""
    return sorted(
        (
            step
            for step in steps_by_uuid.values()
            if step.level == level and step.parent_step_uuid == parent_uuid
        ),
        key=lambda step: step.step_id,
    )


def _union_scope(nodes: list[ScopedNode]) -> tuple[set[str], set[str]]:
    """Union the required_concepts and declared_concepts of nodes.

    Returns (set(), set()) when nodes is empty.
    """
    required: set[str] = set()
    declared: set[str] = set()
    for node in nodes:
        required |= node.required_concepts
        declared |= node.declared_concepts
    return required, declared


def build_atomic_scoped_node(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs: Step,
    ts: Step,
    atomic: Step,
    concept_rows: list[tuple[str, str, list[str]]],
    concepts: list[Concept],
    relations: list[tuple[str, str, str]],
    paragraphs: dict[str, str],
) -> tuple[ScopedNode, dict[str, object]]:
    """Build the leaf ScopedNode for one atomic step (A-NNN) and its summary.

    Resolves the branch via plan_manager.views.branch.resolve_branch(conn,
    plan_uuid, gs.step_id, ts.step_id, atomic.step_id); its scope-aware
    required and declared concept sets and coverage diagnostic via
    plan_manager.scoring.reproduction_scope.leaf_scope(branch,
    concept_rows); its SemanticSummary (C-003) via
    plan_manager.views.atomic_summary.build_atomic_semantic_summary(
    atomic_fields, ts.fields) where atomic_fields is {"name":
    atomic.fields.get("name"), "prompt": atomic.fields.get("prompt"),
    "verification": atomic.fields.get("verification"), "target_file":
    atomic.fields.get("target_file"), "operation":
    atomic.fields.get("operation"), "concepts": atomic.concepts,
    "dependencies": atomic.fields.get("depends_on")}; and its ExpectedScope (C-005) text
    via plan_manager.scoring.reproduction_scope.expected_scope_text(
    plan_manager.views.expected_scope.build_expected_scope(coverage,
    concepts, relations, paragraphs)).

    Returns (node, semantic_summary): node is the ScopedNode with path
    f"{gs.step_id}/{ts.step_id}/{atomic.step_id}", own_text
    semantic_summary["summary_text"], expected_text the rendered expected
    scope, required_concepts/declared_concepts the resolved sets, children
    []; semantic_summary is the full structured dict for the caller to pass
    up to reconstruct_tactical_summary.
    """
    branch = resolve_branch(conn, plan_uuid, gs.step_id, ts.step_id, atomic.step_id)
    required, declared, coverage = leaf_scope(branch, concept_rows)

    atomic_fields = {
        "name": atomic.fields.get("name"),
        "prompt": atomic.fields.get("prompt"),
        "verification": atomic.fields.get("verification"),
        "target_file": atomic.fields.get("target_file"),
        "operation": atomic.fields.get("operation"),
        "concepts": atomic.concepts,
        "dependencies": atomic.fields.get("depends_on"),
    }
    semantic_summary = build_atomic_semantic_summary(atomic_fields, ts.fields)
    scope_text = expected_scope_text(build_expected_scope(coverage, concepts, relations, paragraphs))

    node = ScopedNode(
        path=f"{gs.step_id}/{ts.step_id}/{atomic.step_id}",
        own_text=semantic_summary["summary_text"],
        expected_text=scope_text,
        required_concepts=required,
        declared_concepts=declared,
        children=[],
    )
    return node, semantic_summary


def build_tactical_scoped_node(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs: Step,
    ts: Step,
    steps_by_uuid: dict[uuid.UUID, Step],
    concept_rows: list[tuple[str, str, list[str]]],
    concepts: list[Concept],
    relations: list[tuple[str, str, str]],
    paragraphs: dict[str, str],
) -> tuple[ScopedNode, dict[str, object]]:
    """Build the ScopedNode for one tactical step (T-NNN) and its summary.

    atomic_children is _children(steps_by_uuid, ts.uuid, 5). Builds every
    child via build_atomic_scoped_node first (bottom-up); required and
    declared are the union of the children's required_concepts and
    declared_concepts via _union_scope (set(), set() when there are none).

    tactical_fields is {"description": ts.fields.get("description"),
    "inputs": ts.fields.get("inputs"), "outputs": ts.fields.get("outputs")}.
    reconstructed is
    plan_manager.views.reconstruct_tactical_summary.reconstruct_tactical_summary(
    tactical_fields, child_summaries) where child_summaries is the list of
    semantic_summary dicts returned by build_atomic_scoped_node for each
    atomic child, in atomic_children order. The expected-scope text is
    plan_manager.scoring.reproduction_scope.expected_scope_text(
    plan_manager.views.expected_scope.build_expected_scope(
    plan_manager.scoring.reproduction_scope.aggregated_scope(required),
    concepts, relations, paragraphs)).

    Returns (node, reconstructed): node is the ScopedNode with path
    f"{gs.step_id}/{ts.step_id}", own_text
    reconstructed["summary_text"], expected_text the rendered expected
    scope, required_concepts/declared_concepts the unioned sets, children
    the built atomic ScopedNode list in atomic_children order;
    reconstructed is the full structured dict for the caller to pass up to
    reconstruct_global_summary.
    """
    atomic_children = _children(steps_by_uuid, ts.uuid, 5)
    child_nodes: list[ScopedNode] = []
    child_summaries: list[dict[str, object]] = []
    for atomic in atomic_children:
        node, summary = build_atomic_scoped_node(
            conn, plan_uuid, gs, ts, atomic, concept_rows, concepts, relations, paragraphs
        )
        child_nodes.append(node)
        child_summaries.append(summary)

    required, declared = _union_scope(child_nodes)

    tactical_fields = {
        "description": ts.fields.get("description"),
        "inputs": ts.fields.get("inputs"),
        "outputs": ts.fields.get("outputs"),
    }
    reconstructed = reconstruct_tactical_summary(tactical_fields, child_summaries)
    scope_text = expected_scope_text(
        build_expected_scope(aggregated_scope(required), concepts, relations, paragraphs)
    )

    node = ScopedNode(
        path=f"{gs.step_id}/{ts.step_id}",
        own_text=reconstructed["summary_text"],
        expected_text=scope_text,
        required_concepts=required,
        declared_concepts=declared,
        children=child_nodes,
    )
    return node, reconstructed


def build_global_scoped_node(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs: Step,
    steps_by_uuid: dict[uuid.UUID, Step],
    concept_rows: list[tuple[str, str, list[str]]],
    concepts: list[Concept],
    relations: list[tuple[str, str, str]],
    paragraphs: dict[str, str],
) -> tuple[ScopedNode, dict[str, object]]:
    """Build the ScopedNode for one global step (G-NNN) and its summary.

    tactical_children is _children(steps_by_uuid, gs.uuid, 4). Builds every
    child via build_tactical_scoped_node first (bottom-up); required and
    declared are the union of the children's required_concepts and
    declared_concepts via _union_scope (set(), set() when there are none).

    global_fields is {"description": gs.fields.get("description"),
    "relations": gs.fields.get("relations"), "source_labels":
    gs.fields.get("source_labels")}. reconstructed is
    plan_manager.views.reconstruct_global_summary.reconstruct_global_summary(
    global_fields, child_summaries) where child_summaries is the list of
    reconstructed dicts returned by build_tactical_scoped_node for each
    tactical child, in tactical_children order. The expected-scope text is
    plan_manager.scoring.reproduction_scope.expected_scope_text(
    plan_manager.views.expected_scope.build_expected_scope(
    plan_manager.scoring.reproduction_scope.aggregated_scope(required),
    concepts, relations, paragraphs)).

    Returns (node, reconstructed): node is the ScopedNode with path
    gs.step_id, own_text reconstructed["summary_text"], expected_text the
    rendered expected scope, required_concepts/declared_concepts the
    unioned sets, children the built tactical ScopedNode list in
    tactical_children order; reconstructed is the full structured dict for
    the caller to pass up to reconstruct_plan_summary.
    """
    tactical_children = _children(steps_by_uuid, gs.uuid, 4)
    child_nodes: list[ScopedNode] = []
    child_summaries: list[dict[str, object]] = []
    for ts in tactical_children:
        node, summary = build_tactical_scoped_node(
            conn, plan_uuid, gs, ts, steps_by_uuid, concept_rows, concepts, relations, paragraphs
        )
        child_nodes.append(node)
        child_summaries.append(summary)

    required, declared = _union_scope(child_nodes)

    global_fields = {
        "description": gs.fields.get("description"),
        "relations": gs.fields.get("relations"),
        "source_labels": gs.fields.get("source_labels"),
    }
    reconstructed = reconstruct_global_summary(global_fields, child_summaries)
    scope_text = expected_scope_text(
        build_expected_scope(aggregated_scope(required), concepts, relations, paragraphs)
    )

    node = ScopedNode(
        path=gs.step_id,
        own_text=reconstructed["summary_text"],
        expected_text=scope_text,
        required_concepts=required,
        declared_concepts=declared,
        children=child_nodes,
    )
    return node, reconstructed


def assemble_reproduction_input(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    base_url: str | None,
    timeout: float = 60.0,
) -> tuple[ScopedNode, Callable[[str], list[float]]]:
    """Assemble the root ScopedNode and embed_fn for one plan, ready for
    plan_manager.scoring.reproduction_tree.build_tree(root, base_url, embed_fn).

    Loads the plan's current step tree via
    plan_manager.views.dependency_graph.load_steps(conn, plan_uuid), its
    concept rows via plan_manager.scoring.estimators.load_concept_rows, its
    full Concept records via plan_manager.domain.concept_store.list_concepts,
    its relation tuples via plan_manager.domain.relation_store.list_relations,
    and its HRS paragraph-text map via
    plan_manager.scoring.reproduction_scope.paragraph_text_by_label.

    global_steps is the sorted list of steps_by_uuid values whose level == 3
    (level-3 steps have parent_step_uuid None, so _children is not used for
    this level), ordered ascending by step_id. Builds every one via
    build_global_scoped_node (bottom-up);
    required and declared are the union of the global nodes'
    required_concepts and declared_concepts via _union_scope (set(), set()
    when there are no global steps).

    plan_reconstructed is
    plan_manager.views.reconstruct_plan_summary.reconstruct_plan_summary(
    child_summaries) where child_summaries is the list of reconstructed
    dicts returned by build_global_scoped_node for each global step, in
    global_steps order. The expected-scope text is
    plan_manager.scoring.reproduction_scope.expected_scope_text(
    plan_manager.views.expected_scope.build_expected_scope(
    plan_manager.scoring.reproduction_scope.aggregated_scope(required),
    concepts, relations, paragraphs)).

    embed_fn is a closure over conn, base_url, and timeout: embed_fn(text)
    calls plan_manager.scoring.embedding.embed_text(conn, base_url, text,
    timeout=timeout), returning the cache-first embedding vector for text
    and raising plan_manager.scoring.embedding.EmbeddingUnavailable on
    failure or when base_url does not name a reachable embedding service.

    Returns (root, embed_fn): root is the ScopedNode with path ROOT_PATH
    ("PLAN"), own_text plan_reconstructed["summary_text"], expected_text
    the rendered expected scope, required_concepts/declared_concepts the
    unioned sets, children the built global ScopedNode list in
    global_steps order; embed_fn is the Callable[[str], list[float]]
    described above.
    """
    steps_by_uuid = load_steps(conn, plan_uuid)
    concept_rows = load_concept_rows(conn, plan_uuid)
    concepts = list_concepts(conn, plan_uuid)
    relations = list_relations(conn, plan_uuid)
    paragraphs = paragraph_text_by_label(conn, plan_uuid)

    global_steps = sorted(
        (step for step in steps_by_uuid.values() if step.level == 3),
        key=lambda step: step.step_id,
    )

    child_nodes: list[ScopedNode] = []
    child_summaries: list[dict[str, object]] = []
    for gs in global_steps:
        node, summary = build_global_scoped_node(
            conn, plan_uuid, gs, steps_by_uuid, concept_rows, concepts, relations, paragraphs
        )
        child_nodes.append(node)
        child_summaries.append(summary)

    required, declared = _union_scope(child_nodes)
    plan_reconstructed = reconstruct_plan_summary(child_summaries)
    scope_text = expected_scope_text(
        build_expected_scope(aggregated_scope(required), concepts, relations, paragraphs)
    )

    root = ScopedNode(
        path=ROOT_PATH,
        own_text=plan_reconstructed["summary_text"],
        expected_text=scope_text,
        required_concepts=required,
        declared_concepts=declared,
        children=child_nodes,
    )

    def embed_fn(text: str) -> list[float]:
        return embed_text(conn, base_url, text, timeout=timeout)

    return root, embed_fn
