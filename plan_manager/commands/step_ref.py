"""Shared step reference resolution for command inputs."""

from __future__ import annotations

import uuid

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import parent_path


def canonical_step_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the canonical plan-local path for one step."""
    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


def parent_uuid(nodes: dict[uuid.UUID, Step], step: Step) -> str | None:
    """Return the parent UUID string for one step, if any."""
    if step.parent_step_uuid is None:
        return None
    parent = nodes.get(step.parent_step_uuid)
    if parent is None:
        return None
    return str(parent.uuid)


def parent_canonical_path(nodes: dict[uuid.UUID, Step], step: Step) -> str | None:
    """Return the canonical parent path for one step, if any."""
    if step.parent_step_uuid is None:
        return None
    parent = nodes.get(step.parent_step_uuid)
    if parent is None:
        return None
    return canonical_step_path(nodes, parent)


def resolve_step_ref(
    nodes: dict[uuid.UUID, Step],
    ref: str,
    *,
    not_found_code: str = "STEP_NOT_FOUND",
    ambiguous_code: str = "AMBIGUOUS_STEP_ID",
) -> Step:
    """Resolve a step by UUID, canonical path, or backward-compatible step_id.

    Bare local step ids remain accepted only when they resolve to exactly one
    step in the plan. This deliberately refuses unsafe first-match behavior for
    local tactical and atomic ids such as ``T-001`` and ``A-001``.
    """
    try:
        step_uuid = uuid.UUID(ref)
    except ValueError:
        step_uuid = None
    if step_uuid is not None:
        step = nodes.get(step_uuid)
        if step is None:
            raise DomainCommandError(not_found_code, f"step not found: {ref}")
        return step

    if "/" in ref:
        for step in nodes.values():
            if canonical_step_path(nodes, step) == ref:
                return step
        raise DomainCommandError(not_found_code, f"step not found: {ref}")

    matches = [step for step in nodes.values() if step.step_id == ref]
    if not matches:
        raise DomainCommandError(not_found_code, f"step not found: {ref}")
    if len(matches) > 1:
        paths = sorted(canonical_step_path(nodes, step) for step in matches)
        raise DomainCommandError(
            ambiguous_code,
            f"step_id {ref} resolves to multiple steps",
            {"step_id": ref, "matches": paths},
        )
    return matches[0]
