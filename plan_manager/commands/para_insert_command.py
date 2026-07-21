"""Mutating command inserting one new binding paragraph into a plan's HRS."""

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
from plan_manager.domain import paragraph_store
from plan_manager.hrs.paragraph_edit import insert_paragraph
from plan_manager.commands.para_insert_metadata import get_para_insert_metadata


class ParaInsertCommand(Command):
    """Insert one new binding paragraph at a position in the binding order."""

    name = "para_insert"
    version = "1.0.0"
    descr = "Insert one new binding paragraph into a plan's HRS at a binding-order position."
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
                "text": {
                    "type": "string",
                    "description": (
                        "Markdown text of the new paragraph. Must parse to exactly "
                        "one binding paragraph; an optional '{xxxx} ' label prefix "
                        "supplies the label."
                    ),
                },
                "position": {
                    "type": "integer",
                    "description": (
                        "Zero-based insertion index in the BINDING paragraph order; "
                        "the new paragraph takes this place and later paragraphs "
                        "shift down. Omit to append after the last paragraph. "
                        "Minimum 0, maximum the current binding paragraph count."
                    ),
                    "minimum": 0,
                },
                "label": {
                    "type": "string",
                    "description": (
                        "Explicit four-character base36 label for the new paragraph "
                        "(no braces). Must be unique within the plan. Omit to "
                        "auto-assign a fresh label."
                    ),
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one.",
                },
            },
            "required": ["plan", "text"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate para_insert parameters beyond the base schema check.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict, unchanged beyond the base
            validator's own normalization.

        Raises:
            InvalidParamsError: If text is empty, if position is not a
                non-negative integer, or if cascade_uuid is not a valid
                UUID string.
        """
        params = super().validate_params(params)
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise InvalidParamsError(f"text must be a non-empty string: {text!r}")
        position = params.get("position")
        if position is not None and (not isinstance(position, int) or position < 0):
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
            text = kwargs["text"]
            position = kwargs.get("position")
            label = kwargs.get("label")
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
                created = insert_paragraph(conn, p.uuid, text, position, label, "api", rec)
                # Zero-trust: re-read the stored rows and verify the new paragraph
                # landed with the expected label, position, and text.
                after = paragraph_store.list_paragraphs(conn, p.uuid)
                stored = [row for row in after if row.uuid == created["uuid"]]
                assert len(stored) == 1
                assert stored[0].label == created["label"]
                assert stored[0].position == created["position"]
                assert stored[0].text == created["text"]
            return SuccessResult(data={
                "uuid": str(created["uuid"]),
                "label": created["label"],
                "position": created["position"],
            })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_insert_metadata(cls)
