"""Bug closure discipline: the invariant that a bug closes only after source fix + every downstream impact
are fully handled; re-discovery reopens without destroying history (C-026)."""
from __future__ import annotations

from dataclasses import dataclass, field

from plan_manager.domain.runtime_validation import RuntimeValidationError

# Status literals this invariant reasons about, cited from C-022 (impact), C-024 (fix), C-025 (propagation),
# C-020 (bug) concept text. They are VALUES, not imported symbols, to keep this module self-contained.
IMPACT_OPEN_STATUSES: frozenset[str] = frozenset({"suspected", "confirmed", "pending_resolution", "resolved"})
IMPACT_CLEARED_STATUSES: frozenset[str] = frozenset({"unaffected", "verified"})  # skipped handled separately
PROPAGATION_FINISHED_STATUSES: frozenset[str] = frozenset({"done", "verified", "skipped"})
STATUS_FIXED_SOURCE = "fixed_source"
STATUS_PROPAGATING = "propagating"
STATUS_VERIFIED = "verified"
STATUS_CLOSED = "closed"
STATUS_REOPENED = "reopened"


@dataclass(frozen=True)
class ImpactState:
    status: str
    has_reason: bool = False
    has_owner_decision: bool = False  # for a skipped impact, callers set this to bool(BugImpact.skip_decided_by), the owner-decision marker (gap {0m43})


@dataclass(frozen=True)
class PropagationState:
    status: str


@dataclass(frozen=True)
class ClosureDecision:
    can_close: bool
    blocking_reasons: list[str] = field(default_factory=list)


def evaluate_closure(
    *,
    source_fix_verified: bool,
    impacts: list[ImpactState],
    propagations: list[PropagationState],
    mandatory_todos_closed: bool = True,
    required_cascades_finished: bool = True,
) -> ClosureDecision:
    blocking_reasons: list[str] = []

    if not source_fix_verified:
        blocking_reasons.append("source fix not verified")

    for impact in impacts:
        if impact.status == "skipped":
            if not (impact.has_reason and impact.has_owner_decision):
                blocking_reasons.append("skipped impact missing explicit reason and owner decision")
        elif impact.status in IMPACT_OPEN_STATUSES:
            blocking_reasons.append(f"impact not resolved and verified (status={impact.status})")
        elif impact.status in IMPACT_CLEARED_STATUSES:
            pass
        else:
            blocking_reasons.append(f"unknown impact status {impact.status}")

    for propagation in propagations:
        if propagation.status not in PROPAGATION_FINISHED_STATUSES:
            blocking_reasons.append(f"propagation action not finished (status={propagation.status})")

    if not mandatory_todos_closed:
        blocking_reasons.append("mandatory linked TODO items not closed")

    if not required_cascades_finished:
        blocking_reasons.append("required plan cascades not finished")

    return ClosureDecision(can_close=(len(blocking_reasons) == 0), blocking_reasons=blocking_reasons)


def guard_close(
    *,
    source_fix_verified: bool,
    impacts: list[ImpactState],
    propagations: list[PropagationState],
    mandatory_todos_closed: bool = True,
    required_cascades_finished: bool = True,
) -> None:
    decision = evaluate_closure(
        source_fix_verified=source_fix_verified,
        impacts=impacts,
        propagations=propagations,
        mandatory_todos_closed=mandatory_todos_closed,
        required_cascades_finished=required_cascades_finished,
    )
    if not decision.can_close:
        raise RuntimeValidationError("; ".join(decision.blocking_reasons))


def status_after_source_fix(*, has_open_downstream: bool) -> str:
    return STATUS_PROPAGATING if has_open_downstream else STATUS_FIXED_SOURCE


def reopen_status() -> str:
    return STATUS_REOPENED
