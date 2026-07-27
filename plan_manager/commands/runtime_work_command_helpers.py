"""Shared helpers for the runtime work-layer CRUD commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import uuid

from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.domain.runtime_validation import validate_uuid


_PRIMARY_ANCHOR_DESCRIPTION = (
    "Primary anchor type: one of none, project, file, plan, revision, step, "
    "execution_attempt, review_result, bug, bug_fix, todo."
)


def primary_anchor_schema_properties() -> dict[str, dict[str, Any]]:
    """Return schema properties for the shared primary-anchor input shape."""
    return {
        "anchor_type": {"type": "string", "description": _PRIMARY_ANCHOR_DESCRIPTION},
        "anchor_project_id": {
            "type": "string",
            "format": "uuid",
            "description": "Anchor project UUID (for anchor_type=project or file).",
        },
        "anchor_file_path": {
            "type": "string",
            "description": "Anchor project-relative file path (for anchor_type=file).",
        },
        "anchor_plan_uuid": {
            "type": "string",
            "format": "uuid",
            "description": "Anchor plan UUID (for anchor_type=plan or step).",
        },
        "anchor_revision_uuid": {
            "type": "string",
            "format": "uuid",
            "description": "Anchor revision UUID (for anchor_type=revision or optionally step).",
        },
        "anchor_step_uuid": {
            "type": "string",
            "format": "uuid",
            "description": "Anchor step UUID (for anchor_type=step).",
        },
        "anchor_step_path": {
            "type": "string",
            "description": "Anchor step display path snapshot (diagnostic only).",
        },
        "anchor_ref_id": {
            "type": "string",
            "format": "uuid",
            "description": (
                "Anchor referenced-entity UUID (for execution_attempt, "
                "review_result, bug, bug_fix, or todo anchors)."
            ),
        },
    }


def primary_anchor_metadata_params() -> dict[str, dict[str, Any]]:
    """Return metadata params for the shared primary-anchor input shape."""
    return {
        "anchor_type": {"description": _PRIMARY_ANCHOR_DESCRIPTION, "type": "string", "required": True},
        "anchor_project_id": {
            "description": "Anchor project UUID (for anchor_type=project or file).",
            "type": "string",
            "required": False,
        },
        "anchor_file_path": {
            "description": "Anchor project-relative file path (for anchor_type=file).",
            "type": "string",
            "required": False,
        },
        "anchor_plan_uuid": {
            "description": "Anchor plan UUID (for anchor_type=plan or step).",
            "type": "string",
            "required": False,
        },
        "anchor_revision_uuid": {
            "description": "Anchor revision UUID (for anchor_type=revision or optionally step).",
            "type": "string",
            "required": False,
        },
        "anchor_step_uuid": {
            "description": "Anchor step UUID (for anchor_type=step).",
            "type": "string",
            "required": False,
        },
        "anchor_step_path": {
            "description": "Anchor step display path snapshot (diagnostic only).",
            "type": "string",
            "required": False,
        },
        "anchor_ref_id": {
            "description": (
                "Anchor referenced-entity UUID (for execution_attempt, "
                "review_result, bug, bug_fix, or todo anchors)."
            ),
            "type": "string",
            "required": False,
        },
    }


def build_primary_anchor(
    *,
    anchor_type: str,
    anchor_project_id: str | None = None,
    anchor_file_path: str | None = None,
    anchor_plan_uuid: str | None = None,
    anchor_revision_uuid: str | None = None,
    anchor_step_uuid: str | None = None,
    anchor_step_path: str | None = None,
    anchor_ref_id: str | None = None,
) -> PrimaryAnchor:
    """Parse and build a shared ``PrimaryAnchor`` from command params."""
    return PrimaryAnchor(
        anchor_type=anchor_type,
        project_id=validate_uuid(anchor_project_id) if anchor_project_id is not None else None,
        file_path=anchor_file_path,
        plan_uuid=validate_uuid(anchor_plan_uuid) if anchor_plan_uuid is not None else None,
        revision_uuid=validate_uuid(anchor_revision_uuid) if anchor_revision_uuid is not None else None,
        step_uuid=validate_uuid(anchor_step_uuid) if anchor_step_uuid is not None else None,
        step_path=anchor_step_path,
        ref_id=validate_uuid(anchor_ref_id) if anchor_ref_id is not None else None,
    )


@dataclass(frozen=True)
class ResolvedAnchorScope:
    """Resolved UUID-bearing scope extracted from runtime list filters."""

    project_uuid: uuid.UUID | None
    anchor_plan_uuid: uuid.UUID | None
    revision_uuid: uuid.UUID | None
    step_uuid: uuid.UUID | None


def resolve_anchor_scope(
    conn: Any,
    *,
    project: str | None = None,
    anchor_plan: str | None = None,
    revision: str | None = None,
    step: str | None = None,
) -> ResolvedAnchorScope:
    """Resolve the shared UUID-bearing scope used by runtime work list commands."""
    return ResolvedAnchorScope(
        project_uuid=uuid.UUID(project) if project is not None else None,
        anchor_plan_uuid=resolve_plan(conn, anchor_plan).uuid if anchor_plan is not None else None,
        revision_uuid=validate_uuid(revision) if revision is not None else None,
        step_uuid=validate_uuid(step) if step is not None else None,
    )
