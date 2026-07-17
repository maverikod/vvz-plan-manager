"""Mutating command replacing the text of one HRS paragraph addressed by label."""

from __future__ import annotations

import re
import uuid
from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.views.dependency_graph import load_steps
from plan_manager.domain import paragraph_store
from plan_manager.hrs.paragraph_edit import update_paragraph
from plan_manager.commands.para_update_metadata import get_para_update_metadata

_LABEL_RE = re.compile(r"^[0-9a-z]{4}$")


class ParaUpdateCommand(Command):
    """Replace the text of one existing binding paragraph in place."""

    name = "para_update"
    version = "1.0.0"
    descr = "Replace the text of one binding HRS paragraph addressed by label."
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
                    "description": "Bare four-character base36 label of the binding paragraph to update (no braces).",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Replacement markdown text. Must parse to exactly one "
                        "binding paragraph; a '{xxxx} ' prefix is rejected unless "
                        "it equals the addressed label (no label rewrites)."
                    ),
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": "Open cascade identity (UUID) admitting this mutation when the plan requires one.",
                },
            },
            "required": ["plan", "label", "text"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = super().validate_params(params)
        label = params.get("label", "")
        if not _LABEL_RE.match(label):
            raise ValueError(
                f"label must be exactly four base36 characters [0-9a-z]: {label!r}"
            )
        text = params.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"text must be a non-empty string: {text!r}")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            try:
                uuid.UUID(cascade_uuid)
            except ValueError as exc:
                raise ValueError(f"cascade_uuid is not a valid UUID: {cascade_uuid!r}") from exc
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            label = kwargs["label"]
            text = kwargs["text"]
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
                updated = update_paragraph(conn, p.uuid, label, text, "api", rec)
                # Zero-trust: re-read the stored row and verify text changed in
                # place with uuid, label, and position preserved.
                after = paragraph_store.list_paragraphs(conn, p.uuid)
                stored = [row for row in after if row.uuid == updated["uuid"]]
                assert len(stored) == 1
                assert stored[0].label == label
                assert stored[0].position == updated["position"]
                assert stored[0].text == updated["text"]
            return SuccessResult(data={
                "uuid": str(updated["uuid"]),
                "label": updated["label"],
                "position": updated["position"],
            })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_update_metadata(cls)
