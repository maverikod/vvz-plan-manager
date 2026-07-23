"""Pure level-based role-model resolution over injected candidates (C-006)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.model_binding_inheritance import scope_rank
from plan_manager.domain.role_model_binding import RoleModelBinding
from plan_manager.domain.runtime_validation import RuntimeValidationError


class RoleModelResolutionError(RuntimeValidationError):
    """Raised when role_model_resolve finds no eligible explicit binding, step-level candidate, or role-default candidate for a target; maps to ROLE_MODEL_RESOLUTION_FAILED."""


@dataclass(frozen=True)
class CandidateModel:
    """One injected candidate model: a concrete (provider, model name) pair at a capability level, built by the caller from the entity-core model/provider stores (this module never queries those stores)."""

    name: str
    level: str
    provider: str
    provider_active: bool


@dataclass(frozen=True)
class RoleModelResolutionTarget:
    """The (role, phase, requirement) input to role_model_resolve, plus the pre-filtered candidate bindings the caller supplies for the explicit-binding and role-default resolution steps."""

    role: str
    phase: str | None
    step_required_level: str | None
    role_default_binding: RoleModelBinding | None
    explicit_bindings: tuple[ModelBinding, ...] = ()


@dataclass(frozen=True)
class RoleModelResolutionResult:
    """The outcome of role_model_resolve: the chosen (provider, model) pair, which resolution source produced it, and the provenance detail."""

    source: str
    chosen_provider: str
    chosen_model: str
    chosen_level: str | None
    provenance: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        """Render the RoleModelResolutionResult as a JSON-safe payload dictionary."""
        return {
            "source": self.source,
            "chosen_provider": self.chosen_provider,
            "chosen_model": self.chosen_model,
            "chosen_level": self.chosen_level,
            "provenance": self.provenance,
        }


def _select_explicit_binding(bindings: tuple[ModelBinding, ...]) -> ModelBinding | None:
    """Pick the most specific active explicit ModelBinding from bindings, or None if none is eligible.

    Eligibility: binding.active is True and binding.deleted_at is None.
    Specificity: ranked by scope_rank(binding.scope) ascending; ties broken
    by binding.created_at ascending, then by str(binding.binding_uuid)
    ascending. The LAST element after this ascending sort is the winner
    (highest scope_rank, i.e. most specific).
    """
    eligible = [b for b in bindings if b.active and b.deleted_at is None]
    if not eligible:
        return None
    sorted_eligible = sorted(
        eligible,
        key=lambda b: (scope_rank(b.scope), b.created_at, str(b.binding_uuid)),
    )
    return sorted_eligible[-1]


def _select_candidate_by_level(candidates: Sequence[CandidateModel], level: str) -> CandidateModel | None:
    """Pick the first active CandidateModel of the given level, sorted by name ascending, or None if none matches.

    Eligibility: candidate.level == level and candidate.provider_active is True.
    Deterministic tiebreak: ascending sort by candidate.name; the first
    element of the sorted list is returned.
    """
    eligible = [c for c in candidates if c.level == level and c.provider_active]
    if not eligible:
        return None
    return sorted(eligible, key=lambda c: c.name)[0]


def role_model_resolve(
    target: RoleModelResolutionTarget,
    candidates: Sequence[CandidateModel],
) -> RoleModelResolutionResult:
    """Resolve the concrete (provider, model) for a role-model resolution target.

    Applies, in this exact fixed order, stopping at the first step that
    yields a result:

      (a) Explicit model binding: if target.explicit_bindings contains at
          least one binding with active=True and deleted_at=None, select the
          most specific one via _select_explicit_binding and return a
          RoleModelResolutionResult with source="explicit_binding",
          chosen_provider=<that binding's provider>,
          chosen_model=<that binding's model>, chosen_level=None, and
          provenance={"binding_uuid": str(<binding_uuid>), "scope": <scope>,
          "role": target.role, "phase": target.phase}.

      (b) Step-level requirement: else, if target.step_required_level is not
          None, select the first active CandidateModel of that level via
          _select_candidate_by_level(candidates, target.step_required_level).
          If one is found, return a RoleModelResolutionResult with
          source="step_requirement", chosen_provider=<candidate.provider>,
          chosen_model=<candidate.name>, chosen_level=<candidate.level>, and
          provenance={"role": target.role, "phase": target.phase,
          "required_level": target.step_required_level}. If none is found,
          raise RoleModelResolutionError (do NOT fall through to role
          default in this case).

      (c) Role default: else, if target.role_default_binding is not None and
          target.role_default_binding.active is True and
          target.role_default_binding.deleted_at is None, select the first
          active CandidateModel of level
          target.role_default_binding.required_level via
          _select_candidate_by_level. If one is found, return a
          RoleModelResolutionResult with source="role_default",
          chosen_provider=<candidate.provider>, chosen_model=<candidate.name>,
          chosen_level=<candidate.level>, and provenance={"role": target.role,
          "phase": target.phase, "required_level":
          target.role_default_binding.required_level,
          "role_default_binding_uuid":
          str(target.role_default_binding.binding_uuid)}. If none is found,
          raise RoleModelResolutionError.

      (d) Otherwise (no explicit binding, no step_required_level, no usable
          role_default_binding): raise RoleModelResolutionError.

    Args:
        target: The resolution target (role, phase, step_required_level,
            role_default_binding, explicit_bindings).
        candidates: The candidate models to select from for (b) and (c).

    Returns:
        The RoleModelResolutionResult describing the chosen model and its
        provenance.

    Raises:
        RoleModelResolutionError: When no step above yields a result, per
            the exact conditions enumerated in (b), (c), and (d) above.
    """
    winner_binding = _select_explicit_binding(target.explicit_bindings)
    if winner_binding is not None:
        return RoleModelResolutionResult(
            source="explicit_binding",
            chosen_provider=winner_binding.provider,
            chosen_model=winner_binding.model,
            chosen_level=None,
            provenance={
                "binding_uuid": str(winner_binding.binding_uuid),
                "scope": winner_binding.scope,
                "role": target.role,
                "phase": target.phase,
            },
        )

    if target.step_required_level is not None:
        chosen = _select_candidate_by_level(candidates, target.step_required_level)
        if chosen is None:
            raise RoleModelResolutionError(
                f"no active candidate model of level {target.step_required_level!r} "
                f"for role {target.role!r} step requirement"
            )
        return RoleModelResolutionResult(
            source="step_requirement",
            chosen_provider=chosen.provider,
            chosen_model=chosen.name,
            chosen_level=chosen.level,
            provenance={
                "role": target.role,
                "phase": target.phase,
                "required_level": target.step_required_level,
            },
        )

    if (
        target.role_default_binding is not None
        and target.role_default_binding.active
        and target.role_default_binding.deleted_at is None
    ):
        level = target.role_default_binding.required_level
        chosen = _select_candidate_by_level(candidates, level)
        if chosen is None:
            raise RoleModelResolutionError(
                f"no active candidate model of level {level!r} for role {target.role!r} "
                f"default binding {target.role_default_binding.binding_uuid}"
            )
        return RoleModelResolutionResult(
            source="role_default",
            chosen_provider=chosen.provider,
            chosen_model=chosen.name,
            chosen_level=chosen.level,
            provenance={
                "role": target.role,
                "phase": target.phase,
                "required_level": level,
                "role_default_binding_uuid": str(target.role_default_binding.binding_uuid),
            },
        )

    raise RoleModelResolutionError(
        f"no explicit model binding, step-level requirement, or active role-default "
        f"binding for role {target.role!r}"
    )
