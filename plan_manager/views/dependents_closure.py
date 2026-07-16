"""Transitive dependency-edge closure traversal (C-013 GraphDependents).

Computes the bounded transitive closure over step_dependency (depends_on)
edges from one origin step, steered by a direction switch that selects
dependents-of (forward hops) versus dependencies-of (backward hops). This
traversal is explicitly distinct from plan_manager.views.dependency_graph
.impact_set, which projects the hierarchical-descendant (parent_step_uuid)
relation used by impact analysis and cascade semantics; those stay
unchanged and are not touched by this module. Every function in this
module is a read-only projection: none of them mutate the database or the
nodes/edges passed to them.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import dependents_of, prerequisites_of, tie_break_key


DEFAULT_DEPTH_LIMIT: int = 10
MAX_DEPTH_LIMIT: int = 100

DIRECTIONS: tuple[str, ...] = ("dependents", "dependencies")


def transitive_closure(
    nodes: dict[uuid.UUID, Step],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    origin_uuid: uuid.UUID,
    direction: str,
    depth_limit: int,
) -> list[uuid.UUID]:
    """Compute the bounded transitive closure of one origin step over depends_on edges.

    Args:
        nodes: All steps of the plan, keyed by uuid, as returned by
            plan_manager.views.dependency_graph.load_steps.
        edges: The edge set as returned by
            plan_manager.views.dependency_graph.build_edges: each edge is
            (prerequisite_uuid, dependent_uuid).
        origin_uuid: The uuid of the step whose closure is computed.
        direction: "dependents" follows edges forward from origin_uuid,
            hop by hop, via plan_manager.views.dependency_graph
            .dependents_of (steps that depend, directly or transitively,
            on origin_uuid). "dependencies" follows edges backward, hop
            by hop, via plan_manager.views.dependency_graph
            .prerequisites_of (steps that origin_uuid depends on, directly
            or transitively).
        depth_limit: The maximum number of hops from origin_uuid to
            traverse. Depth 1 returns only the direct neighbors of
            origin_uuid in the selected direction. A depth_limit of 0 or
            a negative value returns an empty list (no hops taken).

    Returns:
        The list of uuids reached within depth_limit hops of origin_uuid
        in the selected direction, origin_uuid excluded, each uuid
        appearing at most once (first hop distance at which it is
        reached), sorted ascending by tie_break_key(nodes, u).

    Raises:
        ValueError: If direction is not one of "dependents",
            "dependencies".
    """
    if direction not in DIRECTIONS:
        raise ValueError(
            f"direction must be one of {DIRECTIONS}, got {direction!r}"
        )
    neighbor_fn = dependents_of if direction == "dependents" else prerequisites_of

    visited: set[uuid.UUID] = {origin_uuid}
    result: list[uuid.UUID] = []
    frontier: list[uuid.UUID] = [origin_uuid]
    depth = 0
    while frontier and depth < depth_limit:
        next_frontier: list[uuid.UUID] = []
        for current_uuid in frontier:
            for neighbor_uuid in neighbor_fn(nodes, edges, current_uuid):
                if neighbor_uuid not in visited:
                    visited.add(neighbor_uuid)
                    result.append(neighbor_uuid)
                    next_frontier.append(neighbor_uuid)
        frontier = next_frontier
        depth += 1

    result.sort(key=lambda u: tie_break_key(nodes, u))
    return result
