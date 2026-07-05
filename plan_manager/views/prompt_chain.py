"""Prompt-chain assembly view for scoped plan execution prompts.

The view is read-only. It turns a gate-green plan scope into a
deduplicated block graph plus atomic execution rows, without adding any
provider-specific prompt markup.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.status_model import ATOMIC_ONLY_STATUSES, STATUSES
from plan_manager.domain.step import Step
from plan_manager.storage.canonical import canonical_json
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import build_edges, load_steps, parent_path, waves
from plan_manager.views.prompt_assembly import mrs_excerpt, step_content


DEFAULT_INCLUDE_STATUSES = ("frozen", "ready_for_review")

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


def normalize_statuses(include_statuses: list[str] | None) -> list[str]:
    """Normalize the status filter used to select eligible atomic branches."""
    values = list(DEFAULT_INCLUDE_STATUSES) if include_statuses is None else include_statuses
    if not values:
        raise ValueError("include_statuses must not be empty")
    allowed = set(STATUSES) | set(ATOMIC_ONLY_STATUSES)
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


def _hrs_content(paragraphs: list[Paragraph]) -> str:
    return "\n\n".join(
        "{" + paragraph.label + "} " + paragraph.text for paragraph in paragraphs
    )


def _block_id(block_type: str, source_ref: list[str], content: str) -> str:
    payload = {
        "type": block_type,
        "source_ref": source_ref,
        "content": content,
    }
    digest = hashlib.sha256(canonical_json(payload)).hexdigest()[:16]
    return f"{block_type.replace('_', '-')}-{digest}"


def _put_block(
    blocks: dict[str, dict],
    block_type: str,
    source_ref: list[str],
    content: str,
) -> str:
    block_id = _block_id(block_type, source_ref, content)
    blocks.setdefault(
        block_id,
        {
            "block_id": block_id,
            "type": block_type,
            "source_ref": source_ref,
            "content": content,
        },
    )
    return block_id


def _wave_index(nodes: dict[uuid.UUID, Step]) -> dict[uuid.UUID, int]:
    edge_set = build_edges(nodes)
    wave_map: dict[uuid.UUID, int] = {}
    for index, wave in enumerate(waves(nodes, edge_set)):
        for node_uuid in wave:
            wave_map[node_uuid] = index
    return wave_map


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


def assemble_prompt_chain(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    plan_name: str,
    revision_uuid: uuid.UUID | None,
    scope: PromptScope,
    include_statuses: list[str],
) -> dict:
    """Assemble the prompt-chain payload for a gate-green scope."""
    nodes = load_steps(conn, plan_uuid)
    paragraphs = list_paragraphs(conn, plan_uuid)
    atomic_steps = eligible_atomic_steps(
        nodes,
        scope_atomic_steps(nodes, scope),
        include_statuses,
    )
    wave_map = _wave_index(nodes)

    blocks: dict[str, dict] = {}
    steps: list[dict] = []
    for atomic in atomic_steps:
        branch = branch_for_atomic(nodes, paragraphs, plan_uuid, atomic)
        branch_path = parent_path(nodes, atomic)
        block_ids = [
            _put_block(
                blocks,
                "hrs_fragment",
                ["{" + paragraph.label + "}" for paragraph in branch.hrs_slice],
                _hrs_content(branch.hrs_slice),
            ),
            _put_block(
                blocks,
                "mrs_fragment",
                sorted(branch.atomic.concepts),
                mrs_excerpt(conn, plan_uuid, branch.atomic.concepts),
            ),
            _put_block(
                blocks,
                "global_step",
                [branch.gs.step_id],
                step_content(branch.gs),
            ),
            _put_block(
                blocks,
                "tactical_step",
                [branch_path],
                step_content(branch.ts),
            ),
            _put_block(
                blocks,
                "atomic_step",
                [artifact_path_of(nodes, branch.atomic)],
                step_content(branch.atomic),
            ),
        ]
        steps.append(
            {
                "step_id": atomic.step_id,
                "target_file": atomic.fields["target_file"],
                "operation": atomic.fields["operation"],
                "priority": atomic.fields["priority"],
                "block_ids": block_ids,
                "wave": wave_map[atomic.uuid],
                "branch_path": branch_path,
                "depends_on": list(atomic.depends_on),
            }
        )

    steps.sort(
        key=lambda row: (
            row["branch_path"],
            row["priority"],
            row["step_id"],
        )
    )
    ordered_blocks = {
        block_id: blocks[block_id]
        for block_id in sorted(blocks)
    }
    return {
        "plan": plan_name,
        "revision": str(revision_uuid) if revision_uuid is not None else None,
        "scope": scope.label,
        "blocks": ordered_blocks,
        "steps": steps,
    }
