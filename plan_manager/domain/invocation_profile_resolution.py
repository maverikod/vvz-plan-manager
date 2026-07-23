"""Invocation profile resolution: select the most specific applicable profile for a target (C-008)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.invocation_profile import InvocationProfile
from plan_manager.domain.model_binding_inheritance import scope_rank
from plan_manager.domain.runtime_validation import RuntimeValidationError


class ProfileResolutionError(RuntimeValidationError):
    """Raised when no invocation profile in the supplied candidate set applies to the target (C-008)."""


@dataclass(frozen=True)
class ProfileResolutionTarget:
    role: str
    plan_uuid: uuid.UUID | None = None
    spec_level: str | None = None
    branch_step_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None


@dataclass(frozen=True)
class InvocationProfileResolution:
    profile: InvocationProfile
    source_scope: str
    source_profile_uuid: uuid.UUID
    inheritance_path: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_payload(),
            "source_scope": self.source_scope,
            "source_profile_uuid": str(self.source_profile_uuid),
            "inheritance_path": self.inheritance_path,
        }


def profile_applies(profile: InvocationProfile, target: ProfileResolutionTarget) -> bool:
    """Return True when profile is active, non-deleted, role-compatible, and scope-matches target."""
    if not profile.active or profile.deleted_at is not None:
        return False

    if not (profile.role is None or profile.role == target.role):
        return False

    if profile.scope == "system":
        return True
    elif profile.scope == "plan":
        return profile.plan_uuid == target.plan_uuid
    elif profile.scope == "level":
        return (profile.plan_uuid == target.plan_uuid) and (profile.spec_level == target.spec_level)
    elif profile.scope == "branch":
        return (profile.plan_uuid == target.plan_uuid) and (profile.branch_step_uuid == target.branch_step_uuid)
    elif profile.scope == "step":
        return (profile.plan_uuid == target.plan_uuid) and (profile.step_uuid == target.step_uuid)
    elif profile.scope == "role":
        return (profile.role == target.role) and (profile.plan_uuid is None or profile.plan_uuid == target.plan_uuid)
    else:
        raise RuntimeValidationError(f"unknown scope: {profile.scope}")


def invocation_profile_resolve(
    candidates: list[InvocationProfile], target: ProfileResolutionTarget
) -> InvocationProfileResolution:
    """Pure resolution over supplied candidates: select the most specific applicable invocation
    profile for target and report it with its inheritance path.

    Mirrors resolve_effective_binding's specificity-then-role-then-plan-then-recency tie-break,
    applied over InvocationProfile candidates instead of ModelBinding candidates. Nothing here
    enforces the winning profile's field values; this function only selects and reports.
    """
    applicable = [p for p in candidates if profile_applies(p, target)]

    if not applicable:
        raise ProfileResolutionError("no applicable invocation profile for target")

    sorted_applicable = sorted(
        applicable,
        key=lambda p: (
            scope_rank(p.scope),
            1 if p.role is not None else 0,
            1 if (p.plan_uuid is not None and p.plan_uuid == target.plan_uuid) else 0,
            p.created_at,
            str(p.profile_uuid),
        ),
    )

    inheritance_path: list[dict[str, Any]] = []
    for p in sorted_applicable:
        inheritance_path.append(
            {
                "scope": p.scope,
                "role": p.role,
                "profile_uuid": str(p.profile_uuid),
                "plan_specific": (p.plan_uuid is not None and p.plan_uuid == target.plan_uuid),
                "selected": False,
            }
        )

    inheritance_path[-1]["selected"] = True

    winner = sorted_applicable[-1]

    return InvocationProfileResolution(
        profile=winner,
        source_scope=winner.scope,
        source_profile_uuid=winner.profile_uuid,
        inheritance_path=inheritance_path,
    )
