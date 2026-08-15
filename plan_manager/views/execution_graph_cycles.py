"""Cycle detection for the extended execution graph (EIG block B, todo 16853f27).

Split out of ``views/execution_graph.py`` to keep that module under the
project's 400-line module cap. Adapts, rather than re-derives, the cycle
machinery ``views/dependency_graph.py`` already ships: ``topological_order``
(Kahn's algorithm) isolates the residual node set that never reaches
indegree zero, and ``cycle_edges`` restricts the edge set to that residual
subgraph. What is genuinely new here is decomposing that residual subgraph
into its individual cycles (Tarjan's strongly-connected-components
algorithm), since Kahn's residual can include nodes merely blocked behind a
cycle, not only nodes that are themselves part of one.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import cycle_edges, tie_break_key, topological_order
from plan_manager.views.step_paths import parent_path

Edge = tuple[uuid.UUID, uuid.UUID]


def _artifact_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the artifact path of ``step`` (duplicated from execution_graph._artifact_path).

    Kept as a private, byte-identical copy (both derive from the same
    ``parent_path`` primitive) rather than imported back from
    execution_graph.py, so this module has no import-order dependency on
    its sibling.
    """
    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


def _tarjan_scc(
    node_set: set[uuid.UUID],
    adjacency: dict[uuid.UUID, list[uuid.UUID]],
    resolver: dict[uuid.UUID, Step],
) -> list[list[uuid.UUID]]:
    """Tarjan's strongly-connected-components algorithm, deterministic order.

    Iterative (explicit work stack) rather than recursive, so component
    size is bounded only by available memory, not Python's recursion limit.
    Neighbor exploration order is sorted by tie_break_key so the same input
    always yields identically-ordered components.
    """
    index_of: dict[uuid.UUID, int] = {}
    lowlink: dict[uuid.UUID, int] = {}
    on_stack: dict[uuid.UUID, bool] = {}
    stack: list[uuid.UUID] = []
    counter = [0]
    components: list[list[uuid.UUID]] = []

    def strongconnect(start: uuid.UUID) -> None:
        work: list[tuple[uuid.UUID, list[uuid.UUID]]] = [
            (start, sorted(adjacency.get(start, []), key=lambda u: tie_break_key(resolver, u)))
        ]
        index_of[start] = counter[0]
        lowlink[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on_stack[start] = True

        while work:
            node, neighbors = work[-1]
            advanced = False
            while neighbors:
                neighbor = neighbors.pop(0)
                if neighbor not in node_set:
                    continue
                if neighbor not in index_of:
                    index_of[neighbor] = counter[0]
                    lowlink[neighbor] = counter[0]
                    counter[0] += 1
                    stack.append(neighbor)
                    on_stack[neighbor] = True
                    work.append(
                        (
                            neighbor,
                            sorted(
                                adjacency.get(neighbor, []),
                                key=lambda u: tie_break_key(resolver, u),
                            ),
                        )
                    )
                    advanced = True
                    break
                if on_stack.get(neighbor):
                    lowlink[node] = min(lowlink[node], index_of[neighbor])
            if advanced:
                continue
            work.pop()
            if work:
                parent_node = work[-1][0]
                lowlink[parent_node] = min(lowlink[parent_node], lowlink[node])
            if lowlink[node] == index_of[node]:
                component: list[uuid.UUID] = []
                while True:
                    member = stack.pop()
                    on_stack[member] = False
                    component.append(member)
                    if member == node:
                        break
                components.append(component)

    for node_uuid in sorted(node_set, key=lambda u: tie_break_key(resolver, u)):
        if node_uuid not in index_of:
            strongconnect(node_uuid)
    return components


def _shortest_cycle_through(
    scc: set[uuid.UUID],
    adjacency: dict[uuid.UUID, list[uuid.UUID]],
    resolver: dict[uuid.UUID, Step],
) -> list[uuid.UUID]:
    """Return one concrete simple cycle path covering part of one SCC.

    Deterministic: starts at the SCC member with the smallest tie_break_key,
    breadth-first-explores the SCC-induced subgraph with sorted neighbor
    order, then closes back to the start via the shortest available direct
    edge into it (ties broken by tie_break_key). Every SCC produced by
    Tarjan's algorithm is strongly connected, so such a closing edge always
    exists once the whole SCC has been visited.
    """
    start = min(scc, key=lambda u: tie_break_key(resolver, u))
    parent: dict[uuid.UUID, uuid.UUID | None] = {start: None}
    order = [start]
    idx = 0
    while idx < len(order):
        current = order[idx]
        idx += 1
        for neighbor in sorted(
            (n for n in adjacency.get(current, []) if n in scc),
            key=lambda u: tie_break_key(resolver, u),
        ):
            if neighbor not in parent:
                parent[neighbor] = current
                order.append(neighbor)

    def depth(node: uuid.UUID) -> int:
        steps = 0
        while parent[node] is not None:
            node = parent[node]  # type: ignore[assignment]
            steps += 1
        return steps

    closers = [u for u in scc if u in parent and start in adjacency.get(u, ())]
    closer = min(closers, key=lambda u: (depth(u), tie_break_key(resolver, u)))
    path: list[uuid.UUID] = []
    current: uuid.UUID | None = closer
    while current is not None:
        path.append(current)
        current = parent[current]
    path.reverse()
    return path


def cycles_report(nodes: dict[uuid.UUID, Step], combined_edges: set[Edge]) -> list[list[str]]:
    """Report every cycle in ``combined_edges`` as a canonically sorted list of ordered paths.

    Args:
        nodes: Every step of the plan, keyed by uuid.
        combined_edges: The full combined (explicit + file_order + inferred)
            edge set in uuid space, each edge (prerequisite_uuid,
            dependent_uuid).

    Returns:
        A canonically sorted list of cycles; each cycle is an ordered list
        of artifact paths (a walk that returns to its own first element via
        one more edge, not repeated at the end of the list). Empty when the
        combined edge set has no cycle.
    """
    _order, residual = topological_order(nodes, combined_edges)
    if not residual:
        return []
    residual_set = set(residual)
    sub_edges = cycle_edges(combined_edges, residual)
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for prereq_uuid, dependent_uuid in sub_edges:
        adjacency.setdefault(prereq_uuid, []).append(dependent_uuid)

    cycles: list[list[str]] = []
    for component in _tarjan_scc(residual_set, adjacency, nodes):
        if len(component) < 2:
            continue
        path = _shortest_cycle_through(set(component), adjacency, nodes)
        cycles.append([_artifact_path(nodes, nodes[u]) for u in path])
    cycles.sort()
    return cycles
