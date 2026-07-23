"""Command: scaffold a new step under a plan's declarative level schema."""

import re
import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission, frozen_at_or_below
from plan_manager.cascade.write import cascade_write, step_snapshot
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.step_create_metadata import get_step_create_metadata
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.domain.project_binding import require_project_bound
from plan_manager.domain.step_store import create_step, get_step
from plan_manager.runtime.context import db_connection
from plan_manager.storage.version_store import record_revision
from plan_manager.views.context_blocks import current_working_state, has_current_common_block
from plan_manager.views.dependency_graph import load_steps


_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


SKELETON_FIELDS: dict[int, dict] = {
    3: {"description": "", "source_labels": []},
    4: {"description": "", "inputs": [], "outputs": []},
    5: {
        "name": "",
        "target_file": "",
        "operation": "create_file",
        "priority": 1,
        "prompt": "",
        "verification": {"type": "manual", "target": "", "expected": ""},
    },
}


class StepCreateCommand(Command):
    """Scaffold a new step with the next free zero-padded identifier."""

    name: ClassVar[str] = "step_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Scaffold a new step under a plan's declarative level schema."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_create.

        Returns:
            A JSON-Schema-shaped dict with `type`, `properties`, `required`,
            and `additionalProperties` keys.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
                },
                "level": {
                    "type": "integer",
                    "description": "Target hierarchy level for the new step: 3 (global step), 4 (tactical step), or 5 (atomic step).",
                    "enum": [3, 4, 5],
                },
                "slug": {
                    "type": "string",
                    "description": "Lowercase kebab-case slug, unique among siblings under the same parent.",
                },
                "parent_step_id": {
                    "type": "string",
                    "description": "Parent step, as UUID, canonical path, or unambiguous local step id; required for levels 4 and 5, must be absent for level 3. A bare local id matching more than one step is rejected with AMBIGUOUS_PARENT_STEP_ID.",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identifier to admit this mutation under; omit for direct-mode mutation on a non-frozen parent.",
                },
                "project_id": {
                    "type": "string",
                    "description": "Optional analysis-server project UUID already bound to the plan.",
                },
            },
            "required": ["plan", "level", "slug"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_create parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If slug is not lowercase kebab-case, if
                parent_step_id is present for level 3, if parent_step_id is
                absent for level 4 or 5, or if cascade_uuid is not a valid
                UUID string.
        """
        params = super().validate_params(params)
        slug = params.get("slug", "")
        if not _SLUG_PATTERN.fullmatch(slug):
            raise InvalidParamsError(f"slug must be lowercase kebab-case: {slug!r}")
        level = params.get("level")
        parent_step_id = params.get("parent_step_id")
        if level == 3 and parent_step_id is not None:
            raise InvalidParamsError("parent_step_id must be absent for level 3")
        if level in (4, 5) and not parent_step_id:
            raise InvalidParamsError(f"parent_step_id is required for level {level}")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            try:
                uuid.UUID(cascade_uuid)
            except ValueError as exc:
                raise InvalidParamsError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
        return params

    async def execute(
        self,
        plan: str,
        level: int,
        slug: str,
        parent_step_id: str | None = None,
        cascade_uuid: str | None = None,
        project_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Scaffold a new step and record it as a revision.

        Args:
            plan: Plan identifier (UUID or name).
            level: Target hierarchy level (3, 4, or 5).
            slug: Lowercase kebab-case slug for the new step.
            parent_step_id: Human-readable step_id of the parent; required
                for levels 4 and 5, must be None for level 3.
            cascade_uuid: Open cascade identifier to admit this mutation
                under, or None for direct-mode mutation.

        Returns:
            SuccessResult with the new step's identity and revision_uuid on
            success, or ErrorResult with a stable domain error code on
            failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                normalized_project_id = (
                    require_project_bound(p, project_id)
                    if project_id is not None
                    else None
                )
                nodes = load_steps(conn, p.uuid)
                parent = None
                parent_uuid = None
                if parent_step_id is not None:
                    parent = resolve_step_ref(
                        nodes,
                        parent_step_id,
                        ambiguous_code="AMBIGUOUS_PARENT_STEP_ID",
                    )
                    parent_uuid = parent.uuid
                parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                target_kind = "paragraph" if parent_uuid is None else "step"
                try:
                    rec = check_admission(conn, p.uuid, target_kind, parent_uuid, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    if parent is not None:
                        if frozen_at_or_below(nodes, parent.uuid):
                            return domain_error("FROZEN_ARTIFACT", str(exc))
                        return domain_error("CASCADE_REQUIRED", str(exc))
                    if any(step.status == "frozen" for step in nodes.values()):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                if parent is not None:
                    parent_path = canonical_step_path(nodes, parent)
                    working_revision, working_cascade = current_working_state(conn, p)
                    if not has_current_common_block(
                        conn, p.uuid, parent_path, level, working_revision, working_cascade,
                    ):
                        return domain_error(
                            "CONTEXT_BLOCKS_MISSING",
                            f"parent {parent_path} has no current context_common block for child_level {level}",
                            {"node": parent_path, "child_level": level},
                        )
                step_fields = dict(SKELETON_FIELDS[level])
                if level == 5:
                    step_fields["verification"] = dict(step_fields["verification"])
                new_step = create_step(
                    conn,
                    p.uuid,
                    parent_uuid,
                    level,
                    slug,
                    step_fields,
                    [],
                    [],
                    normalized_project_id,
                )
                snapshot = step_snapshot(new_step, new_step.status)
                if rec is not None:
                    revision = cascade_write(
                        conn, p.uuid, rec, new_step.uuid, snapshot, [], "api",
                        f"step_create: {new_step.step_id}",
                    )
                else:
                    revision = record_revision(
                        conn, p.uuid, "api", f"step_create: {new_step.step_id}",
                        [(new_step.uuid, snapshot)], p.head_revision_uuid, ref_name=None,
                    )
                verified = get_step(conn, new_step.uuid)
                data = {
                    "uuid": str(verified.uuid),
                    "step_id": verified.step_id,
                    "slug": verified.slug,
                    "level": verified.level,
                    "project_id": verified.project_id,
                    "status": verified.status,
                    "revision_uuid": str(revision),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_create.

        Returns:
            The dict produced by `get_step_create_metadata(cls)`.
        """
        return get_step_create_metadata(cls)
