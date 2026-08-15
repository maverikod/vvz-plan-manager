"""Extended parallel-map derived view (EIG block C, todo 12fd8a80).

Supports graph_parallel_map's ``mode="extended"``: waves computed over the
COMBINED edge set block B's ``views.execution_graph.build_execution_graph``
exposes (explicit + file_order + object_producer + verification_target)
instead of only the declared/derived edges ``views.dependency_graph.
build_edges`` returns, plus four additive payload sections built on top of
that same combined edge set: ``placement_reasons``, ``critical_path``,
``wave_parallelism``, ``conflict_groups``.

Every function here is a read-only, pure projection over an already-loaded
``nodes`` dict, mirroring ``views/execution_graph.py``'s contract: no
database access, no mutation of the arguments.
"""

from __future__ import annotations

import uuid
from typing import Any

from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import tie_break_key
from plan_manager.views.execution_graph import build_execution_graph

Edge = tuple[uuid.UUID, uuid.UUID]

MODE_EXPLICIT = "explicit"
MODE_EXTENDED = "extended"
MODE_VALUES: tuple[str, ...] = (MODE_EXPLICIT, MODE_EXTENDED)


def extended_edges(
    nodes: dict[uuid.UUID, Step],
) -> tuple[set[Edge], list[dict[str, Any]], dict[str, Any]]:
    """Build the combined extended edge set for one plan's node set.

    Calls ``build_execution_graph`` once and resolves its dict-shaped edges
    (artifact-path ``from``/``to``) back to a uuid edge set suitable for
    ``views.dependency_graph.waves``.

    Returns:
        A 3-tuple ``(uuid_edges, edge_dicts, graph)``:
            uuid_edges: the full combined edge set (explicit + file_order +
                object_producer + verification_target) as
                ``(prerequisite_uuid, dependent_uuid)`` pairs.
            edge_dicts: ``graph["explicit_edges"] + graph["inferred_edges"]``
                (from/to are artifact paths, as build_execution_graph
                returns them), canonically sorted.
            graph: the full ``build_execution_graph(nodes)`` result, reused
                by ``build_conflict_groups`` for ``ambiguous_dependencies``.

    Raises:
        SameFileOrderAmbiguousError, ValueError: propagated from
            ``build_execution_graph``/``build_edges`` unchanged.
    """
    graph = build_execution_graph(nodes)
    edge_dicts = graph["explicit_edges"] + graph["inferred_edges"]
    path_to_uuid = {artifact_path_of(nodes, step): node_uuid for node_uuid, step in nodes.items()}
    uuid_edges = {(path_to_uuid[edge["from"]], path_to_uuid[edge["to"]]) for edge in edge_dicts}
    return uuid_edges, edge_dicts, graph


def build_placement_reasons(
    nodes: dict[uuid.UUID, Step],
    edge_dicts: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    """Map each step's artifact path to the incoming edges that pin its wave.

    An edge "pins" a step when the edge's ``to`` is the step itself OR any
    of its ancestors (the ``parent_step_uuid`` chain): wave placement
    inherits ancestor ``depends_on`` constraints (``views.dependency_graph.
    waves``'s ancestor-inheritance step, bug 85a9d14b / todo 19391f0b), so
    an edge landing on an ancestor pins every descendant exactly as it pins
    the ancestor itself. Wave-0 steps always report an empty list: ``waves``
    places a node at depth 0 only when it (and every ancestor) has zero
    effective prerequisites, which is exactly the condition under which no
    edge targets the node or any ancestor.

    Returns:
        A dict from every step's artifact path to the sorted, de-duplicated
        list of ``{"from": <artifact path>, "type": <edge type>}`` pinning
        it, ascending by ``(from, type)``.
    """
    path_of = {node_uuid: artifact_path_of(nodes, step) for node_uuid, step in nodes.items()}
    path_to_uuid = {path: node_uuid for node_uuid, path in path_of.items()}

    children_of: dict[uuid.UUID, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.parent_step_uuid in nodes:
            children_of.setdefault(step.parent_step_uuid, []).append(node_uuid)

    descendant_cache: dict[uuid.UUID, set[uuid.UUID]] = {}

    def _descendants(node_uuid: uuid.UUID) -> set[uuid.UUID]:
        cached = descendant_cache.get(node_uuid)
        if cached is not None:
            return cached
        result = {node_uuid}
        for child_uuid in children_of.get(node_uuid, []):
            result |= _descendants(child_uuid)
        descendant_cache[node_uuid] = result
        return result

    reasons: dict[str, set[tuple[str, str]]] = {path: set() for path in path_of.values()}
    for edge in edge_dicts:
        target_uuid = path_to_uuid.get(edge["to"])
        if target_uuid is None:
            continue
        pin = (edge["from"], edge["type"])
        for descendant_uuid in _descendants(target_uuid):
            reasons[path_of[descendant_uuid]].add(pin)

    return {
        path: [{"from": frm, "type": typ} for frm, typ in sorted(pins)]
        for path, pins in reasons.items()
    }


def build_critical_path(nodes: dict[uuid.UUID, Step], uuid_edges: set[Edge]) -> list[str]:
    """Compute one longest dependency chain over the extended edge set.

    A longest-path DP walk in topological order (Kahn's algorithm, reusing
    ``dependency_graph.tie_break_key``'s ascending ready-set sort so ties
    resolve deterministically exactly like ``topological_order``/``waves``
    do): ``dp[node] = 1 + max(dp[prereq] for prereq in direct
    predecessors)``, zero when there are none; among predecessors tied on
    that max, the one with the smallest ``tie_break_key`` is kept as the
    chosen backpointer. The chain endpoint is the node with the greatest
    ``dp``, ties broken the same way (smallest ``tie_break_key`` wins), then
    walked back through backpointers to reconstruct the chain.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        uuid_edges: The combined extended edge set, assumed acyclic (the
            caller is expected to have already raised CYCLE_DETECTED via
            ``waves(nodes, uuid_edges)`` before calling this).

    Returns:
        The longest chain as a list of artifact paths, oldest (root) first.
        Empty when nodes is empty.
    """
    if not nodes:
        return []
    path_of = {node_uuid: artifact_path_of(nodes, step) for node_uuid, step in nodes.items()}

    predecessors_of: dict[uuid.UUID, list[uuid.UUID]] = {u: [] for u in nodes}
    dependents_of: dict[uuid.UUID, list[uuid.UUID]] = {u: [] for u in nodes}
    indegree: dict[uuid.UUID, int] = {u: 0 for u in nodes}
    for prereq_uuid, dependent_uuid in uuid_edges:
        indegree[dependent_uuid] += 1
        dependents_of[prereq_uuid].append(dependent_uuid)
        predecessors_of[dependent_uuid].append(prereq_uuid)

    ready = [u for u, deg in indegree.items() if deg == 0]
    remaining_indegree = dict(indegree)
    dp_length: dict[uuid.UUID, int] = {}
    dp_prev: dict[uuid.UUID, uuid.UUID | None] = {}
    order: list[uuid.UUID] = []

    while ready:
        ready.sort(key=lambda u: tie_break_key(nodes, u))
        current = ready.pop(0)
        order.append(current)
        best_length = 0
        best_prev: uuid.UUID | None = None
        for prereq_uuid in predecessors_of[current]:
            candidate_length = dp_length[prereq_uuid]
            if candidate_length > best_length or (
                candidate_length == best_length
                and best_prev is not None
                and tie_break_key(nodes, prereq_uuid) < tie_break_key(nodes, best_prev)
            ):
                best_length = candidate_length
                best_prev = prereq_uuid
        dp_length[current] = best_length + 1
        dp_prev[current] = best_prev
        for dependent_uuid in dependents_of[current]:
            remaining_indegree[dependent_uuid] -= 1
            if remaining_indegree[dependent_uuid] == 0:
                ready.append(dependent_uuid)

    if not order:
        return []
    max_length = max(dp_length.values())
    candidates = [u for u in order if dp_length[u] == max_length]
    candidates.sort(key=lambda u: tie_break_key(nodes, u))
    end = candidates[0]

    chain: list[uuid.UUID] = []
    current: uuid.UUID | None = end
    while current is not None:
        chain.append(current)
        current = dp_prev[current]
    chain.reverse()
    return [path_of[u] for u in chain]


def build_conflict_groups(nodes: dict[uuid.UUID, Step], graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Build generalized conflict groups over the extended edge set.

    Two families, both purely informational (waves() already serializes
    same-file writers deterministically via file_order edges when a
    deterministic order exists; this reports the grouping, not an error):

      - "same_file_writers": every ``target_file`` written by 2+ level-5
        steps. Mirrors the ``by_file`` grouping ``views.dependency_graph.
        build_edges``/``views.same_file_order.same_file_order_conflicts``
        derive verbatim (same field, same level==5 filter) rather than
        importing it, for the same reason ``views/execution_graph.py``'s
        ``_explicit_edges`` duplicates a few lines instead of taking on a
        cross-module dependency for a four-line loop.
      - "same_object_producers": ``graph["ambiguous_dependencies"]`` (block
        B), one group per object with more than one distinct producer AS.

    Returns:
        Groups sorted ascending by ``(type, key)``; each group is
        ``{"type", "key", "members"}`` with ``members`` a sorted list of
        artifact paths.
    """
    groups: list[dict[str, Any]] = []

    by_file: dict[str, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            by_file.setdefault(target_file.strip(), []).append(node_uuid)

    for target_file, group_uuids in by_file.items():
        if len(group_uuids) < 2:
            continue
        members = sorted(artifact_path_of(nodes, nodes[u]) for u in group_uuids)
        groups.append({"type": "same_file_writers", "key": target_file, "members": members})

    for entry in graph["ambiguous_dependencies"]:
        groups.append(
            {
                "type": "same_object_producers",
                "key": entry["object"],
                "members": list(entry["producers"]),
            }
        )

    groups.sort(key=lambda g: (g["type"], g["key"]))
    return groups
