"""Pure computation of needs_review invalidation update sets for CascadeChange (C-016).

This module contains no database access and no persistence. Every function
returns a plain list of (uuid.UUID, str) tuples describing status updates to
be applied by the caller inside an open cascade transaction. Illegal status
transitions propagate as StatusTransitionError raised by
plan_manager.domain.status_model.validate_transition.
"""

import uuid

from plan_manager.domain.status_model import validate_transition
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import impact_set


def step_invalidation(
    nodes: dict[uuid.UUID, Step], origin_uuid: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """Compute the invalidation update set for one changed step.

    Realises the transitive needs_review propagation rule for a changed
    step (C-005) inside an open cascade (C-016), driven through the status
    model (C-007): a changed global step invalidates its tactical steps
    and their atomic steps, a changed tactical step invalidates its
    atomic steps. The invalidation set is the transitive descendants of
    origin_uuid by parent linkage, computed by the dependency graph
    projection (C-009).

    Args:
        nodes: Mapping of step uuid.UUID to Step, the loaded plan step
            tree.
        origin_uuid: uuid.UUID of the changed step that anchors the
            invalidation.

    Returns:
        A list of (uuid.UUID, "needs_review") tuples in the deterministic
        order produced by impact_set, one entry per descendant step whose
        status is not already "needs_review". Empty when nothing beneath
        the origin requires invalidation.

    Raises:
        ValueError: if origin_uuid is not a key of nodes ("origin step
            not in tree").
        StatusTransitionError: propagated from validate_transition when a
            descendant step's current status cannot legally transition to
            "needs_review" via cascade.
    """
    if origin_uuid not in nodes:
        raise ValueError("origin step not in tree")
    updates: list[tuple[uuid.UUID, str]] = []
    for descendant_uuid in impact_set(nodes, origin_uuid):
        descendant = nodes[descendant_uuid]
        if descendant.status == "needs_review":
            continue
        validate_transition(
            descendant.status,
            "needs_review",
            is_atomic_step=(descendant.level == 5),
            via_cascade=True,
        )
        updates.append((descendant_uuid, "needs_review"))
    return updates


def mrs_invalidation(nodes: dict[uuid.UUID, Step]) -> list[tuple[uuid.UUID, str]]:
    """Compute the invalidation update set for a changed MRS entity or paragraph.

    Realises the rule that an HRS change triggers MRS re-projection and an
    MRS change invalidates all global steps (C-016), driven through the
    status model (C-007): every global step (Step.level == 3) of the plan
    whose status is not already "needs_review" is included in the update
    set, per the rule that a changed MRS entity or a changed paragraph
    invalidates every global step of the plan.

    Args:
        nodes: Mapping of step uuid.UUID to Step, the loaded plan step
            tree.

    Returns:
        A list of (uuid.UUID, "needs_review") tuples, one entry per
        global step (Step.level == 3) whose status is not already
        "needs_review", sorted by Step.step_id ascending. Empty when
        every global step is already "needs_review".

    Raises:
        StatusTransitionError: propagated from validate_transition when a
            global step's current status cannot legally transition to
            "needs_review" via cascade.
    """
    updates: list[tuple[uuid.UUID, str]] = []
    global_steps = sorted(
        (s for s in nodes.values() if s.level == 3 and s.status != "needs_review"),
        key=lambda s: s.step_id,
    )
    for step in global_steps:
        validate_transition(
            step.status,
            "needs_review",
            is_atomic_step=False,
            via_cascade=True,
        )
        updates.append((step.uuid, "needs_review"))
    return updates
