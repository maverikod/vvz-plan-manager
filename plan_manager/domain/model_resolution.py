"""Effective model resolution: pick the winning binding for a (step, role) and report provenance (C-012)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.model_binding_inheritance import scope_rank


class ModelResolutionError(RuntimeValidationError):
    ...


@dataclass(frozen=True)
class ResolutionTarget:
    role: str
    plan_uuid: uuid.UUID | None = None
    spec_level: str | None = None
    branch_step_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None


@dataclass(frozen=True)
class ModelResolution:
    effective_provider: str
    effective_model: str
    source: str
    source_binding_uuid: uuid.UUID
    fallback_provider: str | None
    fallback_model: str | None
    retry_count: int
    timeout: int
    context_budget: int | None
    inheritance_path: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        return {
            "effective_provider": self.effective_provider,
            "effective_model": self.effective_model,
            "source": self.source,
            "source_binding_uuid": str(self.source_binding_uuid),
            "fallback_provider": self.fallback_provider,
            "fallback_model": self.fallback_model,
            "retry_count": self.retry_count,
            "timeout": self.timeout,
            "context_budget": self.context_budget,
            "inheritance_path": self.inheritance_path,
        }


def binding_applies(binding: ModelBinding, target: ResolutionTarget) -> bool:
    if not binding.active or binding.deleted_at is not None:
        return False

    if not (binding.role is None or binding.role == target.role):
        return False

    if binding.scope == "system":
        return True
    elif binding.scope == "plan":
        return binding.plan_uuid == target.plan_uuid
    elif binding.scope == "level":
        return (binding.plan_uuid == target.plan_uuid) and (binding.spec_level == target.spec_level)
    elif binding.scope == "branch":
        return (binding.plan_uuid == target.plan_uuid) and (binding.branch_step_uuid == target.branch_step_uuid)
    elif binding.scope == "step":
        return (binding.plan_uuid == target.plan_uuid) and (binding.step_uuid == target.step_uuid)
    elif binding.scope == "role":
        return (binding.role == target.role) and (binding.plan_uuid is None or binding.plan_uuid == target.plan_uuid)
    else:
        raise RuntimeValidationError(f"unknown scope: {binding.scope}")


def resolve_effective_binding(candidates: list[ModelBinding], target: ResolutionTarget) -> ModelResolution:
    applicable = [b for b in candidates if binding_applies(b, target)]

    if not applicable:
        raise ModelResolutionError("no applicable model binding for target")

    sorted_applicable = sorted(
        applicable,
        key=lambda b: (
            scope_rank(b.scope),
            1 if b.role is not None else 0,
            1 if (b.plan_uuid is not None and b.plan_uuid == target.plan_uuid) else 0,
            b.created_at,
            str(b.binding_uuid),
        ),
    )

    inheritance_path = []
    for b in sorted_applicable:
        inheritance_path.append(
            {
                "scope": b.scope,
                "role": b.role,
                "binding_uuid": str(b.binding_uuid),
                "provider": b.provider,
                "model": b.model,
                "plan_specific": (b.plan_uuid is not None and b.plan_uuid == target.plan_uuid),
                "selected": False,
            }
        )

    inheritance_path[-1]["selected"] = True

    winner = sorted_applicable[-1]

    return ModelResolution(
        effective_provider=winner.provider,
        effective_model=winner.model,
        source=winner.scope,
        source_binding_uuid=winner.binding_uuid,
        fallback_provider=winner.fallback_provider,
        fallback_model=winner.fallback_model,
        retry_count=winner.max_retries,
        timeout=winner.timeout,
        context_budget=winner.context_budget,
        inheritance_path=inheritance_path,
    )
