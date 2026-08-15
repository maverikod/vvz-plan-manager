"""Shared computation for the execution_dependency_suggest/apply pair (EIG block D, todo 004cd507).

Materializes a subset of the extended execution graph (EIG block B,
``views.execution_graph.build_execution_graph``) into a
``step_dependency_apply``-compatible ``depends_on`` change proposal: the
INFERRED ``object_producer``/``verification_target`` edges that are (a) not
ambiguous (their object is absent from ``ambiguous_dependencies``) and (b)
not already implied by the explicit graph (no existing path, direct or
transitive, from producer to consumer).

Cross-branch rule: every inferred edge here connects two atomic (level-5)
steps (block-A object roles and AS verification/target_file pairs are only
ever computed at level 5). ``step_dependency_ops.resolve_dependency_bare``
already admits a level-5-to-level-5 dependency across tactical/global
branches directly, storing it as a canonical step path (see
``tests/test_cross_branch_step_dependencies.py``), unlike GS/TS depends_on
which stays sibling-scoped. So no ancestor-level lifting (the
``derive_cross_branch_edges``/``waves()``-inheritance technique used to
order same-file writers, which have no other per-AS channel to express
cross-branch order) is needed or correct here: every proposed change is
expressed directly at the atomic step's own level, with both the target
step_id and the depends_on reference given as the full canonical path
(``edge["to"]``/``edge["from"]`` from ``build_execution_graph``), which
resolves correctly whether the pair is sibling or cross-branch.
"""

from __future__ import annotations

import uuid
from typing import Any

from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.execution_graph import build_execution_graph
from plan_manager.views.same_file_order import reachable


def compute_suggested_changes(nodes: dict[uuid.UUID, Step]) -> dict[str, Any]:
    """Compute the unambiguous, not-already-implied inferred-edge proposal.

    Args:
        nodes: The full node set of one plan, as returned by
            ``views.dependency_graph.load_steps``.

    Returns:
        A dict with keys:
            "proposed_changes": a step_dependency_apply-compatible list of
                {"op": "add", "step_id": <consumer canonical path>,
                "depends_on": [<producer canonical path>, ...]}, one entry
                per consumer step gaining at least one edge, sorted by
                step_id, each depends_on list deduplicated and sorted.
            "proposed_edges": the surviving inferred edge dicts (from, to,
                type, provenance, evidence) backing proposed_changes, in the
                canonical order build_execution_graph already sorts them in.
            "ambiguous_dependencies": build_execution_graph's full
                {object, producers} list — the skipped-as-ambiguous report;
                every object_producer edge naming one of these objects is
                excluded from proposed_edges/proposed_changes.
            "missing_producers": build_execution_graph's full
                {object, consumers} list, passed through for context.

    Raises:
        SameFileOrderAmbiguousError: propagated from build_execution_graph
            when the plan's current same-file writer order is ambiguous.
        ValueError: propagated from build_execution_graph when a declared
            depends_on reference cannot be resolved.
    """
    graph = build_execution_graph(nodes)
    edges = build_edges(nodes)
    path_to_uuid = {
        canonical_step_path(nodes, step): node_uuid for node_uuid, step in nodes.items()
    }
    ambiguous_objects = {entry["object"] for entry in graph["ambiguous_dependencies"]}

    proposed_edges: list[dict[str, Any]] = []
    proposed_by_step: dict[str, list[str]] = {}
    for edge in graph["inferred_edges"]:
        if edge["type"] == "object_producer" and edge["evidence"]["object"] in ambiguous_objects:
            continue
        producer_uuid = path_to_uuid[edge["from"]]
        consumer_uuid = path_to_uuid[edge["to"]]
        if reachable(edges, producer_uuid, consumer_uuid):
            continue  # already implied by the explicit graph
        proposed_edges.append(edge)
        proposed_by_step.setdefault(edge["to"], []).append(edge["from"])

    proposed_changes = [
        {"op": "add", "step_id": step_path, "depends_on": sorted(set(deps))}
        for step_path, deps in sorted(proposed_by_step.items())
    ]
    return {
        "proposed_changes": proposed_changes,
        "proposed_edges": proposed_edges,
        "ambiguous_dependencies": graph["ambiguous_dependencies"],
        "missing_producers": graph["missing_producers"],
    }
