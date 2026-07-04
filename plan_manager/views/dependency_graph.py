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
        "fields, depends_on, concepts, status FROM step WHERE plan_uuid = %s"
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
                status=status,
            )
    return nodes


def parent_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Compute the parent path string of one step for tie-breaking.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        step: The step whose parent path is computed.

    Returns:
        "" when step.level == 3 (no parent). The parent's step_id when
        step.level == 4 (e.g. "G-001"). The parent-of-parent's step_id
        joined with "/" to the parent's step_id when step.level == 5
        (e.g. "G-001/T-002").

    Raises:
        ValueError: If step.level is 4 or 5 and step.parent_step_uuid is
            missing from nodes. The message names step.step_id.
    """
    if step.level == 3:
        return ""
    parent = nodes.get(step.parent_step_uuid)
    if parent is None:
        raise ValueError(f"parent of step {step.step_id} not found in nodes")
    if step.level == 4:
        return parent.step_id
    grandparent = nodes.get(parent.parent_step_uuid)
    if grandparent is None:
        raise ValueError(f"parent of step {step.step_id} not found in nodes")
    return f"{grandparent.step_id}/{parent.step_id}"


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


def build_edges(nodes: dict[uuid.UUID, Step]) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """Build the full edge set of the dependency graph.

    Edge direction is (prerequisite_uuid, dependent_uuid). Two normative
    sources of edges are combined:

    (1) For every step S and every entry d in S.depends_on, the sibling
    step P with P.plan_uuid == S.plan_uuid, P.parent_step_uuid ==
    S.parent_step_uuid, P.level == S.level, P.step_id == d gives edge
    (P.uuid, S.uuid). A depends_on entry that names no existing sibling
    raises ValueError naming S.step_id and d.

    (2) Level-5 steps are grouped by (fields["target_file"],
    parent_step_uuid). Each group is sorted ascending by
    fields["priority"]. An edge is added between each consecutive pair
    in that sorted order: (lower-priority uuid, higher-priority uuid).

    Args:
        nodes: All steps of the plan, keyed by uuid.

    Returns:
        The set of (prerequisite_uuid, dependent_uuid) edges from both
        sources combined.

    Raises:
        ValueError: If a depends_on entry names no existing sibling.
            The message names the dependent step's step_id and the
            unresolved depends_on entry.
    """
    edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    for dependent_uuid, dependent in nodes.items():
        for dep_step_id in dependent.depends_on:
            match = None
            for candidate_uuid, candidate in nodes.items():
                if (
                    candidate.plan_uuid == dependent.plan_uuid
                    and candidate.parent_step_uuid == dependent.parent_step_uuid
                    and candidate.level == dependent.level
                    and candidate.step_id == dep_step_id
                ):
                    match = candidate_uuid
                    break
            if match is None:
                raise ValueError(
                    f"step {dependent.step_id} depends_on unresolved sibling {dep_step_id}"
                )
            edges.add((match, dependent_uuid))

    groups: dict[tuple[str, uuid.UUID | None], list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        key = (step.fields["target_file"], step.parent_step_uuid)
        groups.setdefault(key, []).append(node_uuid)

    for group_uuids in groups.values():
        ordered = sorted(group_uuids, key=lambda u: nodes[u].fields["priority"])
        for lower_uuid, higher_uuid in zip(ordered, ordered[1:]):
            edges.add((lower_uuid, higher_uuid))

    return edges


def topological_order(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Compute Kahn's topological order with deterministic tie-break.

    At every extraction step, among the nodes currently ready (all
    prerequisites already extracted), the node with the smallest
    tie_break_key(nodes, node_uuid) is extracted next.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).

    Returns:
        A 2-tuple (order, cycle_nodes). order is the list of node uuids
        in extraction order. When every node is extracted, cycle_nodes
        is []. When the ready set becomes empty before all nodes are
        extracted, order holds the extracted prefix and cycle_nodes
        holds the remaining (residual) node uuids sorted ascending by
        tie_break_key.
    """
    indegree: dict[uuid.UUID, int] = {u: 0 for u in nodes}
    dependents_map: dict[uuid.UUID, list[uuid.UUID]] = {u: [] for u in nodes}
    for prereq_uuid, dependent_uuid in edges:
        indegree[dependent_uuid] += 1
        dependents_map[prereq_uuid].append(dependent_uuid)

    ready = [u for u, deg in indegree.items() if deg == 0]
    order: list[uuid.UUID] = []
    remaining_indegree = dict(indegree)

    while ready:
        ready.sort(key=lambda u: tie_break_key(nodes, u))
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
    residual.sort(key=lambda u: tie_break_key(nodes, u))
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
) -> list[list[uuid.UUID]]:
    """Partition nodes into parallel waves by prerequisite depth.

    Wave 0 holds every node with no prerequisites. Wave N+1 holds every
    unassigned node all of whose prerequisites lie in waves 0..N. Each
    wave is sorted ascending by tie_break_key.

    Args:
        nodes: All steps of the plan, keyed by uuid.
        edges: The edge set as returned by build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).

    Returns:
        The list of waves in order, each wave a list of node uuids
        sorted ascending by tie_break_key.

    Raises:
        ValueError: With message "cycle detected", if a pass assigns no
            new node while unassigned nodes remain.
    """
    prereqs_of: dict[uuid.UUID, set[uuid.UUID]] = {u: set() for u in nodes}
    for prereq_uuid, dependent_uuid in edges:
        prereqs_of[dependent_uuid].add(prereq_uuid)

    assigned: set[uuid.UUID] = set()
    result: list[list[uuid.UUID]] = []
    unassigned = set(nodes)

    while unassigned:
        wave = [
            u for u in unassigned if prereqs_of[u].issubset(assigned)
        ]
        if not wave:
            raise ValueError("cycle detected")
        wave.sort(key=lambda u: tie_break_key(nodes, u))
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

