"""Mutating command assigning fresh labels to unlabeled binding paragraphs."""

from __future__ import annotations

import uuid
from typing import Any, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.views.dependency_graph import load_steps
from plan_manager.hrs.paragraphs import list_paragraphs, assign_labels
from plan_manager.commands.para_label_assign_metadata import get_para_label_assign_metadata


class ParaLabelAssignCommand(Command):
    """Insert fresh unique four-character base36 labels into unlabeled binding paragraphs."""

    name = "para_label_assign"
    version = "1.0.0"
    descr = "Assign fresh labels to unlabeled binding paragraphs of a plan's HRS."
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
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate para_label_assign parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
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
                labels = assign_labels(conn, p.uuid, "api", rec)
                after = list_paragraphs(conn, p.uuid)
                for para in after:
                    if para["binding"]:
                        assert para["label"] is not None
            return SuccessResult(data={"assigned": labels, "count": len(labels)})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_label_assign_metadata(cls)
