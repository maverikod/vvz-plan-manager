"""One-shot normalization helpers for legacy level-5 object declarations."""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from plan_manager.cascade.write import step_snapshot
from plan_manager.domain.step import Step
from plan_manager.domain.step_objects import (
    normalize_as_object_declarations,
    validate_as_objects,
)
from plan_manager.domain.step_store import update_step_fields
from plan_manager.storage.version_store import record_revision


@dataclass(frozen=True)
class StepObjectRewrite:
    step: Step
    path: str
    fields: dict[str, Any]


def plan_step_object_rewrites(
    nodes: Mapping[uuid.UUID, Step],
    path_of,
) -> tuple[list[StepObjectRewrite], list[dict[str, Any]]]:
    """Return convertible legacy rewrites and non-convertible invalid rows."""
    rewrites: list[StepObjectRewrite] = []
    invalid_steps: list[dict[str, Any]] = []
    atomic_steps = sorted(
        (step for step in nodes.values() if step.level == 5),
        key=path_of,
    )
    for step in atomic_steps:
        fields = step.fields
        if "objects" not in fields:
            continue
        if not validate_as_objects(fields):
            continue
        normalized, problems = normalize_as_object_declarations(
            fields, allow_legacy_strings=True
        )
        path = path_of(step)
        if problems:
            invalid_steps.append({"path": path, "problems": problems})
            continue
        if normalized != fields.get("objects"):
            new_fields = dict(fields)
            new_fields["objects"] = normalized
            rewrites.append(StepObjectRewrite(step=step, path=path, fields=new_fields))
    return rewrites, invalid_steps


def persist_step_object_rewrites(
    conn,
    plan_uuid: uuid.UUID,
    rewrites: list[StepObjectRewrite],
    *,
    parent_revision_uuid: uuid.UUID | None,
    ref_name: str | None,
    author: str,
    message: str,
) -> uuid.UUID | None:
    """Persist one revision for the given rewrites, or return None for a no-op."""
    if not rewrites:
        return None
    for rewrite in rewrites:
        update_step_fields(conn, rewrite.step.uuid, rewrite.fields)
    changes = [
        (
            rewrite.step.uuid,
            step_snapshot(
                dataclasses.replace(rewrite.step, fields=rewrite.fields),
                rewrite.step.status,
            ),
        )
        for rewrite in rewrites
    ]
    return record_revision(
        conn,
        plan_uuid,
        author,
        message,
        changes,
        parent_revision_uuid,
        ref_name,
    )
