"""Mutating command wrapping or unwrapping non-binding markers around a block."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.views.dependency_graph import load_steps
from plan_manager.hrs.paragraphs import list_paragraphs, set_non_binding
from plan_manager.commands.para_mark_non_binding_metadata import get_para_mark_non_binding_metadata


class ParaMarkNonBindingCommand(Command):
    """Wrap or unwrap the non-binding markers around the block at a given position."""

    name = "para_mark_non_binding"
    version = "1.0.0"
    descr = "Wrap or unwrap the non-binding markers around one HRS block of a plan."
    category = "paragraph"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or catalog name) to resolve.",
                },
                "position": {
                    "type": "integer",
                    "description": "Zero-based position of the HRS block to wrap or unwrap. Minimum 0.",
                    "minimum": 0,
                },
                "direction": {
                    "type": "string",
                    "description": "Whether to wrap the block in non-binding markers or unwrap it.",
                    "enum": ["wrap", "unwrap"],
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one.",
                },
            },
            "required": ["plan", "position", "direction"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate para_mark_non_binding parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If position is not a non-negative integer,
                or if cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        position = params.get("position")
        if not isinstance(position, int) or position < 0:
            raise InvalidParamsError(f"position must be an integer >= 0: {position!r}")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            try:
                uuid.UUID(cascade_uuid)
            except ValueError as exc:
                raise InvalidParamsError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            position = kwargs["position"]
            direction = kwargs["direction"]
            cascade_uuid = kwargs.get("cascade_uuid")
            parsed_cascade_uuid = uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                try:
                    rec = check_admission(conn, p.uuid, "paragraph", None, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    steps = load_steps(conn, p.uuid)
                    if any(step.status == "frozen" for step in steps.values()):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                try:
                    set_non_binding(conn, p.uuid, position, direction == "wrap", "api", rec)
                except ValueError:
                    return domain_error("PARAGRAPH_NOT_FOUND", f"no block at position {position}")
                after = list_paragraphs(conn, p.uuid)
                expected_binding = direction == "unwrap"
                for para in after:
                    if para["position"] == position:
                        assert para["binding"] == expected_binding
                        break
            return SuccessResult(data={"position": position, "direction": direction})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_mark_non_binding_metadata(cls)
