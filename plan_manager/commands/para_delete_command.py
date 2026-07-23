"""Mutating command deleting one HRS paragraph addressed by label."""

from __future__ import annotations

import re
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
from plan_manager.domain import paragraph_store
from plan_manager.hrs.paragraph_edit import delete_paragraph
from plan_manager.commands.para_delete_metadata import get_para_delete_metadata

_LABEL_RE = re.compile(r"^[0-9a-z]{4}$")


class ParaDeleteCommand(Command):
    """Delete one binding paragraph by label and close the position gap."""

    name = "para_delete"
    version = "1.0.0"
    descr = "Delete one binding HRS paragraph addressed by label, shifting later paragraphs up."
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
                "label": {
                    "type": "string",
                    "description": "Bare four-character base36 label of the binding paragraph to delete (no braces).",
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one.",
                },
            },
            "required": ["plan", "label"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate para_delete parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If label is not exactly four base36
                characters, or if cascade_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        label = params.get("label", "")
        if not _LABEL_RE.match(label):
            raise InvalidParamsError(
                f"label must be exactly four base36 characters [0-9a-z]: {label!r}"
            )
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
            label = kwargs["label"]
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
                deleted = delete_paragraph(conn, p.uuid, label, "api", rec)
                # Zero-trust: re-read the stored rows and verify the row is gone
                # and no binding row carries the label anymore.
                after = paragraph_store.list_all_paragraphs(conn, p.uuid)
                assert all(row.uuid != deleted["uuid"] for row in after)
                assert all(
                    row.label != label for row in after if row.binding
                )
            return SuccessResult(data={
                "uuid": str(deleted["uuid"]),
                "label": deleted["label"],
                "position": deleted["position"],
                "deleted": True,
            })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_delete_metadata(cls)
