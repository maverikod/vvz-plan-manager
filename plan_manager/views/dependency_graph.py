"""Dependency graph derived view (C-009) for plan_manager.

Computes execution order, cycle detection, parallel waves, dependency
neighborhoods, and impact sets over plan steps (C-005). Every function in
this module is a read-only projection: none of them mutate the database
or the nodes/edges passed to them.
"""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.step import Step
from plan_manager.views.step_paths import (
    GraphIntegrityError,
    parent_path,
    resolve_dependency_target,
)
from plan_manager.views.same_file_order import (
    SameFileOrderAmbiguousError,
    derive_cross_branch_edges,
    same_file_order_conflicts,
)


def load_steps(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict[uuid.UUID, Step]:
    """Load every step row of one plan and build Step objects.

    Issues a single read-only SELECT over the step table for all rows
    whose plan_uuid column equals the given plan_uuid, and builds one
    Step object per row. Issues no INSERT, UPDATE, or DELETE statement.

    Args:
        conn: An open psycopg 3 Connection.
        plan_uuid: The plan (C-001) whose steps are loaded.

    Returns:
        A dict mapping each step's uuid to its Step object, containing
        every step row of the plan regardless of level.
    """
    query = (
        "SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
        "fields, depends_on, concepts, project_id, status FROM step WHERE plan_uuid = %s"
    )
    nodes: dict[uuid.UUID, Step] = {}
    with conn.cursor() as cur:
        cur.execute(query, (plan_uuid,))
        for row in cur.fetchall():
            (
                row_uuid,
                row_plan_uuid,
                parent_step_uuid,
                level,
                step_id,
                slug,
                fields,
                depends_on,
                concepts,
                project_id,
                status,
            ) = row
            nodes[row_uuid] = Step(
                uuid=row_uuid,
                plan_uuid=row_plan_uuid,
                parent_step_uuid=parent_step_uuid,
                level=level,
                step_id=step_id,
                slug=slug,
                fields=fields,
                depends_on=list(depends_on) if depends_on else [],
                concepts=list(concepts) if concepts else [],
                project_id=project_id,
                status=status,
            )
    return nodes


def tie_break_key(nodes: dict[uuid.UUID, Step], node_uuid: uuid.UUID) -> tuple[int, str, str]:
    """Compute the normative ascending tie-break key of one node.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        node_uuid: The uuid of the step to compute the key for.

    Returns:
        (step.level, parent_path(nodes, step), step.step_id) for the
        step identified by node_uuid.
    """
    step = nodes[node_uuid]
    return (step.level, parent_path(nodes, step), step.step_id)


def build_edges(
    nodes: dict[uuid.UUID, Step], *, strict_same_file_order: bool = True
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Build declared and deterministic same-file execution edges.

    Same-file atomic steps under one tactical parent are serialized by priority.
    Across branches, an atomic edge is derived only when declared dependencies
    between their ancestor branches establish one direction. Ambiguous cross-
    branch writers remain unordered and are reported by the mechanical gate.
    """
    edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    for dependent_uuid, dependent in nodes.items():
        for dep_ref in dependent.depends_on:
            target = resolve_dependency_target(nodes, dependent, dep_ref)
            if target is None:
                raise ValueError(
                    f"step {dependent.step_id} depends_on unresolved target {dep_ref}"
                )
            edges.add((target.uuid, dependent_uuid))

    by_parent_file: dict[tuple[str, uuid.UUID | None], list[uuid.UUID]] = {}
    by_file: dict[str, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        priority = step.fields.get("priority")
        if not isinstance(target_file, str) or not target_file.strip() or not isinstance(priority, int):
            continue
        by_parent_file.setdefault((target_file, step.parent_step_uuid), []).append(node_uuid)
        by_file.setdefault(target_file, []).append(node_uuid)

    for group_uuids in by_parent_file.values():
        ordered = sorted(group_uuids, key=lambda u: nodes[u].fields["priority"])
        for lower_uuid, higher_uuid in zip(ordered, ordered[1:]):
            edges.add((lower_uuid, higher_uuid))

    derive_cross_branch_edges(nodes, edges, by_file)
    if strict_same_file_order:
        conflicts = same_file_order_conflicts(nodes, edges)
        if conflicts:
            raise SameFileOrderAmbiguousError(conflicts)
    return edges


def topological_order(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    key_nodes: dict[uuid.UUID, Step] | None = None,
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Compute Kahn's topological order with deterministic tie-break.

    At every extraction step, among the nodes currently ready (all
    prerequisites already extracted), the node with the smallest
    tie_break_key(nodes, node_uuid) is extracted next.

    Args:
        nodes: The steps to order, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).
        key_nodes: Optional superset of nodes used only to resolve the
            tie-break key (parent_path). Pass the full plan node set when
            nodes is a level-restricted subset whose parent steps live
            outside nodes. Defaults to nodes.

    Returns:
        A 2-tuple (order, cycle_nodes). order is the list of node uuids
        in extraction order. When every node is extracted, cycle_nodes
        is []. When the ready set becomes empty before all nodes are
        extracted, order holds the extracted prefix and cycle_nodes
        holds the remaining (residual) node uuids sorted ascending by
        tie_break_key.
    """
    resolver = nodes if key_nodes is None else key_nodes
    indegree: dict[uuid.UUID, int] = {u: 0 for u in nodes}
    dependents_map: dict[uuid.UUID, list[uuid.UUID]] = {u: [] for u in nodes}
    for prereq_uuid, dependent_uuid in edges:
        indegree[dependent_uuid] += 1
        dependents_map[prereq_uuid].append(dependent_uuid)

    ready = [u for u, deg in indegree.items() if deg == 0]
    order: list[uuid.UUID] = []
    remaining_indegree = dict(indegree)

    while ready:
        ready.sort(key=lambda u: tie_break_key(resolver, u))
        current = ready.pop(0)
        order.append(current)
        for dependent_uuid in dependents_map[current]:
            remaining_indegree[dependent_uuid] -= 1
            if remaining_indegree[dependent_uuid] == 0:
                ready.append(dependent_uuid)

    ordered_set = set(order)
    residual = [u for u in nodes if u not in ordered_set]
    if not residual:
        return order, []
    residual.sort(key=lambda u: tie_break_key(resolver, u))
    return order, residual


def cycle_edges(
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    cycle_nodes: list[uuid.UUID],
) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Compute the edges of the residual cycle subgraph.

    Args:
        edges: The full edge set as returned by build_edges.
        cycle_nodes: The residual node uuids as returned as the second
            element of topological_order.

    Returns:
        The subset of edges whose prerequisite_uuid and dependent_uuid
        both appear in cycle_nodes.
    """
    cycle_set = set(cycle_nodes)
    return {
        (prereq_uuid, dependent_uuid)
        for prereq_uuid, dependent_uuid in edges
        if prereq_uuid in cycle_set and dependent_uuid in cycle_set
    }


def waves(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    key_nodes: dict[uuid.UUID, Step] | None = None,
) -> list[list[uuid.UUID]]:
    """Partition nodes into parallel waves by prerequisite depth.

    Wave 0 holds every node with no prerequisites. Wave N+1 holds every
    unassigned node all of whose prerequisites lie in waves 0..N. Each
    wave is sorted ascending by tie_break_key.

    A prerequisite stands for its ENTIRE subtree (todo 19391f0b): a node
    whose own or inherited depends_on names step P is scheduled strictly
    after P and every descendant of P, so a dependent subtree never
    overlaps the producer subtree it waits on. Ancestor depends_on edges
    are inherited by every descendant (bug 85a9d14b), since sibling-scoped
    step_dependency cannot restate them at deeper levels.

    Args:
        nodes: The steps to partition, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).
        key_nodes: Optional superset of nodes used only to resolve the
            tie-break key (parent_path). Pass the full plan node set when
            nodes is a level-restricted subset (e.g. atomic steps only)
            whose parent steps live outside nodes. Defaults to nodes.

    Returns:
        The list of waves in order, each wave a list of node uuids
        sorted ascending by tie_break_key.

    Raises:
        ValueError: With message "cycle detected", if a pass assigns no
            new node while unassigned nodes remain.
    """
    resolver = nodes if key_nodes is None else key_nodes
    explicit_prereqs_of: dict[uuid.UUID, set[uuid.UUID]] = {u: set() for u in nodes}
    for prereq_uuid, dependent_uuid in edges:
        explicit_prereqs_of[dependent_uuid].add(prereq_uuid)

    # Strict subtree closure (todo 19391f0b): a prerequisite step stands for
    # its ENTIRE subtree. Waiting only for the prerequisite node itself let
    # the tail of a producer goal's subtree share a wave with the first
    # steps of the dependent subtree, so a wave-parallel executor could run
    # a consumer concurrently with the producer step it needs.
    descendants_of: dict[uuid.UUID, set[uuid.UUID]] = {u: set() for u in nodes}
    for node_uuid, step in nodes.items():
        ancestor_uuid = step.parent_step_uuid
        while ancestor_uuid in descendants_of:
            descendants_of[ancestor_uuid].add(node_uuid)
            ancestor_uuid = nodes[ancestor_uuid].parent_step_uuid

    # graph_parallel_map ranges over the full tree, but step_dependency is
    # sibling-scoped. A descendant therefore cannot restate an ancestor's
    # declared depends_on edge at its own level, so every node inherits the
    # explicit prerequisite set of its ancestor chain when we compute waves.
    effective_prereqs_of: dict[uuid.UUID, set[uuid.UUID]] = {}

    def _effective_prereqs(node_uuid: uuid.UUID) -> set[uuid.UUID]:
        cached = effective_prereqs_of.get(node_uuid)
        if cached is not None:
            return cached
        inherited: set[uuid.UUID] = set()
        for prereq_uuid in explicit_prereqs_of[node_uuid]:
            inherited.add(prereq_uuid)
            inherited.update(descendants_of[prereq_uuid])
        parent_uuid = nodes[node_uuid].parent_step_uuid
        if parent_uuid in nodes:
            inherited.update(_effective_prereqs(parent_uuid))
        inherited.discard(node_uuid)
        effective_prereqs_of[node_uuid] = inherited
        return inherited

    assigned: set[uuid.UUID] = set()
    result: list[list[uuid.UUID]] = []
    unassigned = set(nodes)

    while unassigned:
        wave = [
            u for u in unassigned if _effective_prereqs(u).issubset(assigned)
        ]
        if not wave:
            raise ValueError("cycle detected")
        wave.sort(key=lambda u: tie_break_key(resolver, u))
        result.append(wave)
        assigned.update(wave)
        unassigned.difference_update(wave)

    return result


def prerequisites_of(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    node_uuid: uuid.UUID,
) -> list[uuid.UUID]:
    """List the direct prerequisites of one node.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).
        node_uuid: The uuid of the node whose prerequisites are listed.

    Returns:
        The uuids p such that (p, node_uuid) is in edges, sorted
        ascending by tie_break_key.
    """
    result = [p for p, d in edges if d == node_uuid]
    result.sort(key=lambda u: tie_break_key(nodes, u))
    return result


def dependents_of(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    node_uuid: uuid.UUID,
) -> list[uuid.UUID]:
    """List the direct dependents of one node.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).
        node_uuid: The uuid of the node whose dependents are listed.

    Returns:
        The uuids d such that (node_uuid, d) is in edges, sorted
        ascending by tie_break_key.
    """
    result = [d for p, d in edges if p == node_uuid]
    result.sort(key=lambda u: tie_break_key(nodes, u))
    return result


def impact_set(nodes: dict[uuid.UUID, Step], origin_uuid: uuid.UUID) -> list[uuid.UUID]:
    """Compute the invalidation-rule impact set of one origin node.

    The impact set is every transitive child of origin_uuid via
    parent_step_uuid chains (children, their children, and so on),
    excluding origin_uuid itself. This is a pure computation: it reads
    nodes only and performs no database mutation.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        origin_uuid: The uuid of the step whose hypothetical change is
            the origin of the impact query.

    Returns:
        The list of transitive child uuids, origin_uuid excluded,
        sorted ascending by tie_break_key.
    """
    children_of: dict[uuid.UUID | None, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        children_of.setdefault(step.parent_step_uuid, []).append(node_uuid)

    result: list[uuid.UUID] = []
    frontier = [origin_uuid]
    while frontier:
        next_frontier: list[uuid.UUID] = []
        for current_uuid in frontier:
            for child_uuid in children_of.get(current_uuid, []):
                result.append(child_uuid)
                next_frontier.append(child_uuid)
        frontier = next_frontier

    result.sort(key=lambda u: tie_break_key(nodes, u))
    return result
