"""Scope selection and normalization for the prompt-chain view.

Mechanically split out of :mod:`plan_manager.views.prompt_chain` (EIG block
G): that module had grown past the repository's ~400-line cap, and the
cleanest seam is between DECIDING WHAT IS IN SCOPE -- parameter
normalization, structural selection, status eligibility, per-branch views --
and ASSEMBLING THE CORPUS from it. Everything here is the former half, moved
verbatim with no behavior change; ``prompt_chain`` re-exports every public
name, so ``from plan_manager.views.prompt_chain import normalize_scope`` (and
every other existing import) keeps working unchanged.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.status_model import STATUSES
from plan_manager.domain.step import Step
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import parent_path

DEFAULT_INCLUDE_STATUSES = ("frozen", "ready_for_review")
ROLES = ("coder", "review", "conscience")

_GLOBAL_SCOPE_RE = re.compile(r"^G-\d{3}$")
_TACTICAL_SCOPE_RE = re.compile(r"^(G-\d{3})/(T-\d{3})$")


@dataclass(frozen=True)
class PromptScope:
    """Resolved prompt-chain scope."""

    label: str
    gs_step_id: str | None
    ts_step_id: str | None


def normalize_scope(scope: str | None) -> PromptScope:
    """Normalize and validate a prompt-chain scope string."""
    if scope is None or scope == "" or scope == "whole_plan":
        return PromptScope("whole_plan", None, None)
    if _GLOBAL_SCOPE_RE.match(scope):
        return PromptScope(scope, scope, None)
    tactical = _TACTICAL_SCOPE_RE.match(scope)
    if tactical is not None:
        return PromptScope(scope, tactical.group(1), tactical.group(2))
    raise ValueError(
        "scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'"
    )


def normalize_role(role: str | None) -> str:
    """Normalize the role selector used by assembly manifests."""
    value = "coder" if role is None or role == "" else role
    if value not in ROLES:
        raise ValueError(f"role must be one of {list(ROLES)}")
    return value


def normalize_statuses(include_statuses: list[str] | None) -> list[str]:
    """Normalize the status filter used to select eligible branches."""
    values = list(DEFAULT_INCLUDE_STATUSES) if include_statuses is None else include_statuses
    if not values:
        raise ValueError("include_statuses must not be empty")
    allowed = set(STATUSES)
    unknown = sorted({status for status in values if status not in allowed})
    if unknown:
        raise ValueError(f"unknown status in include_statuses: {unknown}")
    return sorted(set(values))


def scope_atomic_steps(
    nodes: dict[uuid.UUID, Step],
    scope: PromptScope,
) -> list[Step]:
    """Return all atomic steps structurally contained in ``scope``."""
    if scope.gs_step_id is not None and not any(
        step.level == 3 and step.step_id == scope.gs_step_id for step in nodes.values()
    ):
        raise ValueError(f"no global step found for scope {scope.gs_step_id!r}")
    if scope.ts_step_id is not None and not any(
        step.level == 4
        and step.step_id == scope.ts_step_id
        and parent_path(nodes, step) == scope.gs_step_id
        for step in nodes.values()
    ):
        raise ValueError(f"no tactical step found for scope {scope.label!r}")

    result = []
    for step in nodes.values():
        if step.level != 5:
            continue
        branch_path = parent_path(nodes, step)
        if scope.gs_step_id is not None and not branch_path.startswith(
            scope.gs_step_id + "/"
        ):
            continue
        if scope.ts_step_id is not None and branch_path != scope.label:
            continue
        result.append(step)
    result.sort(
        key=lambda step: (
            parent_path(nodes, step),
            step.fields.get("priority", 0),
            step.step_id,
        )
    )
    return result


def _ancestor_chain(nodes: dict[uuid.UUID, Step], atomic: Step) -> tuple[Step, Step, Step]:
    ts = nodes[atomic.parent_step_uuid]
    gs = nodes[ts.parent_step_uuid]
    return gs, ts, atomic


def eligible_atomic_steps(
    nodes: dict[uuid.UUID, Step],
    atomic_steps: list[Step],
    include_statuses: list[str],
) -> list[Step]:
    """Filter atomic steps whose GS, TS, and AS statuses are included."""
    allowed = set(include_statuses)
    eligible = []
    for atomic in atomic_steps:
        gs, ts, current = _ancestor_chain(nodes, atomic)
        if gs.status in allowed and ts.status in allowed and current.status in allowed:
            eligible.append(atomic)
    return eligible


def hrs_slice_for(
    paragraphs: list[Paragraph],
    gs: Step,
) -> list[Paragraph]:
    """Return the HRS paragraphs referenced by a global step."""
    bare = {
        label[1:-1] if label.startswith("{") and label.endswith("}") else label
        for label in gs.fields.get("source_labels", [])
    }
    return [
        paragraph
        for paragraph in paragraphs
        if paragraph.label is not None and paragraph.label in bare
    ]


def branch_for_atomic(
    nodes: dict[uuid.UUID, Step],
    paragraphs: list[Paragraph],
    plan_uuid: uuid.UUID,
    atomic: Step,
) -> Branch:
    """Construct an in-memory Branch view for one atomic step."""
    gs, ts, current = _ancestor_chain(nodes, atomic)
    return Branch(
        plan_uuid=plan_uuid,
        gs=gs,
        ts=ts,
        atomic=current,
        hrs_slice=hrs_slice_for(paragraphs, gs),
    )
