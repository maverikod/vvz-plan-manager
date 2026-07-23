"""Read-only owner-context assembly (C-011): given one escalation and one owner level, mechanically returns the complete owner packet. Mutates nothing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg

from plan_manager.domain.escalation import Escalation
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import load_steps
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.storage.escalation_store import list_escalations
from plan_manager.storage.escalation_routing_store import assemble_chain
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.concept_store import list_concepts


class OwnerLevel(str, Enum):
    """The four owner levels an escalation can be assembled for (C-011)."""

    TACTICAL = "tactical"
    GLOBAL = "global"
    PLAN = "plan"
    USER = "user"


@dataclass(frozen=True)
class OwnerContextPacket:
    """The read-only owner packet returned by assemble_owner_context. `level` is the OwnerLevel value the packet was assembled for. `escalation_uuid` is the escalation that triggered assembly. `step_path` is the canonical path of the tactical or global step the packet is scoped to, or None for PLAN/USER packets which are not scoped to one step. `payload` is the level-specific content dict (see assemble_owner_context for its exact shape per level)."""

    level: str
    escalation_uuid: uuid.UUID | None
    step_path: str | None
    payload: dict[str, Any]


def assemble_owner_context(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID,
    escalation: Escalation,
    level: OwnerLevel | str,
) -> OwnerContextPacket:
    """Assemble an owner context packet for one escalation at one owner level.

    Args:
        conn: database connection for read-only queries.
        plan_uuid: the plan UUID for loading steps and plan-level data.
        escalation: the escalation whose context is being assembled.
        level: the owner level (OwnerLevel or string matching one of its values).

    Returns:
        OwnerContextPacket: the assembled packet containing level-specific content.

    Raises:
        ValueError: if level is an unrecognized string, if an escalation lacks
            anchor_step_uuid when level is TACTICAL or GLOBAL, or if an anchor
            step level is not reachable for the requested owner level.

    Mutates nothing; issues only read-only queries via the imported store/view functions.
    """
    resolved_level = level if isinstance(level, OwnerLevel) else OwnerLevel(level)

    if resolved_level is OwnerLevel.TACTICAL:
        nodes = load_steps(conn, plan_uuid)
        if escalation.anchor_step_uuid is None:
            raise ValueError(
                "escalation has no anchor_step_uuid; cannot assemble a step-scoped owner context"
            )
        anchor_step = nodes.get(escalation.anchor_step_uuid)
        if anchor_step is None:
            raise ValueError(
                f"anchor step {escalation.anchor_step_uuid} not found in plan {plan_uuid}"
            )
        if anchor_step.level == 5:
            tactical_step = nodes.get(anchor_step.parent_step_uuid)
        elif anchor_step.level == 4:
            tactical_step = anchor_step
        else:
            raise ValueError(
                f"anchor step level {anchor_step.level} is not tactical-reachable for a TACTICAL owner packet"
            )
        if tactical_step is None:
            raise ValueError(
                f"parent tactical step of {anchor_step.uuid} not found in plan {plan_uuid}"
            )
        atomic_children = sorted(
            (s for s in nodes.values() if s.parent_step_uuid == tactical_step.uuid),
            key=lambda s: s.step_id,
        )
        chain = assemble_chain(conn, escalation.escalation_uuid)
        payload = {
            "tactical_step": tactical_step.to_payload(),
            "atomic_steps": [s.to_payload() for s in atomic_children],
            "escalation_chain": [link.to_payload() for link in chain],
        }
        step_path = canonical_step_path(nodes, tactical_step)
        return OwnerContextPacket(
            level=resolved_level.value,
            escalation_uuid=escalation.escalation_uuid,
            step_path=step_path,
            payload=payload,
        )

    elif resolved_level is OwnerLevel.GLOBAL:
        nodes = load_steps(conn, plan_uuid)
        if escalation.anchor_step_uuid is None:
            raise ValueError(
                "escalation has no anchor_step_uuid; cannot assemble a step-scoped owner context"
            )
        anchor_step = nodes.get(escalation.anchor_step_uuid)
        if anchor_step is None:
            raise ValueError(
                f"anchor step {escalation.anchor_step_uuid} not found in plan {plan_uuid}"
            )
        if anchor_step.level == 3:
            global_step = anchor_step
        elif anchor_step.level == 4:
            global_step = nodes.get(anchor_step.parent_step_uuid)
        elif anchor_step.level == 5:
            parent_tactical = nodes.get(anchor_step.parent_step_uuid)
            global_step = (
                nodes.get(parent_tactical.parent_step_uuid)
                if parent_tactical is not None
                else None
            )
        else:
            raise ValueError(
                f"anchor step level {anchor_step.level} is not global-reachable for a GLOBAL owner packet"
            )
        if global_step is None:
            raise ValueError(
                f"parent global step of {anchor_step.uuid} not found in plan {plan_uuid}"
            )
        tactical_children = sorted(
            (s for s in nodes.values() if s.parent_step_uuid == global_step.uuid),
            key=lambda s: s.step_id,
        )
        payload = {
            "global_step": global_step.to_payload(),
            "tactical_steps": [s.to_payload() for s in tactical_children],
        }
        step_path = canonical_step_path(nodes, global_step)
        return OwnerContextPacket(
            level=resolved_level.value,
            escalation_uuid=escalation.escalation_uuid,
            step_path=step_path,
            payload=payload,
        )

    elif resolved_level is OwnerLevel.PLAN:
        paragraphs = list_paragraphs(conn, plan_uuid)
        concepts = list_concepts(conn, plan_uuid)
        payload = {
            "paragraphs": [
                {
                    "uuid": str(p.uuid),
                    "label": p.label,
                    "text": p.text,
                    "position": p.position,
                }
                for p in paragraphs
            ],
            "concepts": [c.to_payload() for c in concepts],
        }
        return OwnerContextPacket(
            level=resolved_level.value,
            escalation_uuid=escalation.escalation_uuid,
            step_path=None,
            payload=payload,
        )

    elif resolved_level is OwnerLevel.USER:
        open_escalations = list_escalations(conn, status="open")
        register: list[dict[str, Any]] = []
        for esc in open_escalations:
            chain = assemble_chain(conn, esc.escalation_uuid)
            register.append(
                {"escalation": esc.to_payload(), "chain": [link.to_payload() for link in chain]}
            )
        payload = {"open_escalations": register}
        return OwnerContextPacket(
            level=resolved_level.value,
            escalation_uuid=escalation.escalation_uuid,
            step_path=None,
            payload=payload,
        )

    else:
        raise ValueError(f"unsupported owner level: {resolved_level!r}")
