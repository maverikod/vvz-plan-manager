"""Command: return a flat, paginated listing of a plan's steps with full step fields."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import parse_pagination
from plan_manager.commands.step_list_metadata import get_step_list_metadata
from plan_manager.commands.step_list_schema import get_step_list_schema
from plan_manager.commands.step_ref import (
    canonical_step_path,
    parent_canonical_path,
    parent_uuid,
    resolve_step_ref,
)
from plan_manager.domain.step import Step
from plan_manager.runtime.context import db_connection
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.views.dependency_graph import load_steps

ENTRY_KEYS: frozenset[str] = frozenset({
    'uuid',
    'step_id',
    'slug',
    'level',
    'project_id',
    'status',
    'parent_path',
    'parent_uuid',
    'fields',
    'depends_on',
    'concepts',
    'path',
    'artifact_path',
})


def _build_entry(nodes: dict[uuid.UUID, Step], step: Step) -> dict[str, Any]:
    """Build the full-field entry dict for one step."""
    return {
        "uuid": str(step.uuid),
        "step_id": step.step_id,
        "slug": step.slug,
        "level": step.level,
        "project_id": step.project_id,
        "status": step.status,
        "parent_path": parent_canonical_path(nodes, step),
        "parent_uuid": parent_uuid(nodes, step),
        "fields": step.fields,
        "depends_on": step.depends_on,
        "concepts": step.concepts,
        "path": canonical_step_path(nodes, step),
        "artifact_path": artifact_path_of(nodes, step),
    }


def _matches_filters(
    entry: dict[str, Any],
    level: int | None,
    parent_uuid_filter: str | None,
    status: str | None,
    target_file: str | None,
) -> bool:
    """Return True when entry satisfies every provided filter."""
    if level is not None and entry["level"] != level:
        return False
    if parent_uuid_filter is not None and entry["parent_uuid"] != parent_uuid_filter:
        return False
    if status is not None and entry["status"] != status:
        return False
    if target_file is not None and entry["fields"].get("target_file") != target_file:
        return False
    return True


def _project(entry: dict[str, Any], field_names: list[str] | None) -> dict[str, Any]:
    """Return entry unchanged, or projected to only the given key names."""
    if field_names is None:
        return entry
    keep = set(field_names)
    return {k: v for k, v in entry.items() if k in keep}


class StepListCommand(Command):
    """Return a flat, paginated listing of a plan's steps with full step fields."""

    name: ClassVar[str] = "step_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return a flat, paginated listing of a plan's steps with full step fields, filterable by level, parent, status, and target_file."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_list."""
        return get_step_list_schema()

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_list parameters, adding projection-key semantics."""
        params = super().validate_params(params)
        fields = params.get("fields")
        if fields is not None:
            if not all(isinstance(name, str) and name in ENTRY_KEYS for name in fields):
                raise ValueError(f"fields must only name known entry keys: {sorted(ENTRY_KEYS)}")
        return params

    async def execute(
        self,
        plan: str,
        level: int | None = None,
        parent: str | None = None,
        status: str | None = None,
        target_file: str | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return a flat, paginated listing of a plan's steps with full step fields."""
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                nodes = load_steps(conn, p.uuid)
                parent_uuid_filter: str | None = None
                if parent is not None:
                    parent_step = resolve_step_ref(nodes, parent)
                    parent_uuid_filter = str(parent_step.uuid)
                entries = []
                for s in nodes.values():
                    entry = _build_entry(nodes, s)
                    if _matches_filters(entry, level, parent_uuid_filter, status, target_file):
                        entries.append(entry)
                entries.sort(key=lambda entry: (entry["level"], entry["path"]))
                total = len(entries)
                page = entries[pagination.offset : pagination.offset + pagination.limit]
                page = [_project(entry, fields) for entry in page]
                return SuccessResult(data={
                    "steps": page,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_list."""
        return get_step_list_metadata(cls)
