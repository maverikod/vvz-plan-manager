"""Command: create a typed link between two runtime records (bug or todo)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_link_command_metadata import runtime_link_metadata
from plan_manager.domain.runtime_link import RUNTIME_LINK_ENTITY_TYPES, RUNTIME_LINK_TYPES
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_link_store import create_runtime_link


class RuntimeLinkAddCommand(Command):
    name: ClassVar[str] = "runtime_link_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a typed link between two runtime records, each independently a bug or a todo."
    category: ClassVar[str] = "runtime_link"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "from_entity_type": {
                    "type": "string",
                    "enum": sorted(RUNTIME_LINK_ENTITY_TYPES),
                    "description": "Type of the source entity (bug or todo).",
                },
                "from_entity_uuid": {
                    "type": "string",
                    "format": "uuid",
                    "description": "UUID of the source entity.",
                },
                "to_entity_type": {
                    "type": "string",
                    "enum": sorted(RUNTIME_LINK_ENTITY_TYPES),
                    "description": "Type of the target entity (bug or todo).",
                },
                "to_entity_uuid": {
                    "type": "string",
                    "format": "uuid",
                    "description": "UUID of the target entity.",
                },
                "link_type": {
                    "type": "string",
                    "enum": sorted(RUNTIME_LINK_TYPES),
                    "description": "Type of link relationship.",
                },
                "created_by": {
                    "type": "string",
                    "description": "User or system identifier creating the link.",
                },
            },
            "required": ["from_entity_type", "from_entity_uuid", "to_entity_type", "to_entity_uuid", "link_type", "created_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        if "from_entity_uuid" in params:
            uuid.UUID(params.get("from_entity_uuid"))
        if "to_entity_uuid" in params:
            uuid.UUID(params.get("to_entity_uuid"))
        from_entity_type = params.get("from_entity_type")
        from_entity_uuid = params.get("from_entity_uuid")
        to_entity_type = params.get("to_entity_type")
        to_entity_uuid = params.get("to_entity_uuid")
        if from_entity_type == to_entity_type and from_entity_uuid == to_entity_uuid:
            raise RuntimeValidationError("a runtime link may not reference the same record as both source and target")
        return params

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = {
            "from_entity_type": {
                "description": "Type of the source entity (bug or todo).",
                "type": "string",
                "enum": sorted(RUNTIME_LINK_ENTITY_TYPES),
                "required": True,
            },
            "from_entity_uuid": {
                "description": "UUID of the source entity.",
                "type": "string",
                "format": "uuid",
                "required": True,
            },
            "to_entity_type": {
                "description": "Type of the target entity (bug or todo).",
                "type": "string",
                "enum": sorted(RUNTIME_LINK_ENTITY_TYPES),
                "required": True,
            },
            "to_entity_uuid": {
                "description": "UUID of the target entity.",
                "type": "string",
                "format": "uuid",
                "required": True,
            },
            "link_type": {
                "description": "Type of link relationship.",
                "type": "string",
                "enum": sorted(RUNTIME_LINK_TYPES),
                "required": True,
            },
            "created_by": {
                "description": "User or system identifier creating the link.",
                "type": "string",
                "required": True,
            },
        }
        return_value = {
            "success": {
                "description": "The created RuntimeLink payload.",
            }
        }
        examples = [
            {
                "description": "Create a blocking link from one todo to another.",
                "command": {
                    "from_entity_type": "todo",
                    "from_entity_uuid": "11111111-1111-1111-1111-111111111111",
                    "to_entity_type": "todo",
                    "to_entity_uuid": "22222222-2222-2222-2222-222222222222",
                    "link_type": "blocks",
                    "created_by": "user@example.com",
                },
            },
            {
                "description": "Create a relates_to link between a bug and a todo.",
                "command": {
                    "from_entity_type": "bug",
                    "from_entity_uuid": "33333333-3333-3333-3333-333333333333",
                    "to_entity_type": "todo",
                    "to_entity_uuid": "44444444-4444-4444-4444-444444444444",
                    "link_type": "relates_to",
                    "created_by": "user@example.com",
                },
            },
        ]
        error_cases = {
            "DUPLICATE_LINK": {
                "description": "An active link with the same endpoints and link_type already exists.",
                "message": "duplicate link: {candidate!r}",
                "solution": "List existing links with runtime_link_list before creating a duplicate.",
            },
            "LINK_CYCLE": {
                "description": "The requested blocking link would introduce a cycle in the combined bug/todo blocking graph.",
                "message": "cycle detected: <node -> ... -> node>",
                "solution": "Remove or invert an existing blocking link before adding this one.",
            },
        }
        return runtime_link_metadata(
            cls,
            parameters,
            return_value,
            examples,
            error_cases=error_cases,
            best_practices=[
                "A runtime link connects two runtime records, each independently a bug or a todo; pass each endpoint's own uuid, not a link uuid.",
                "Blocking link types (blocks, blocked_by) are cycle-guarded across the combined bug/todo blocking graph; a link that would close a cycle is rejected with LINK_CYCLE.",
                "An active link with identical endpoints and link_type is rejected with DUPLICATE_LINK; call runtime_link_list first to check for an existing link.",
                "An endpoint may not link to itself: identical from/to entity_type and entity_uuid is rejected before any write.",
                "Every successful create writes an audit record to the runtime audit trail (entity_type='runtime_link', action='create').",
            ],
        )

    async def execute(
        self,
        from_entity_type: str,
        from_entity_uuid: str,
        to_entity_type: str,
        to_entity_uuid: str,
        link_type: str,
        created_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                record = create_runtime_link(
                    conn,
                    from_entity_type=from_entity_type,
                    from_entity_uuid=uuid.UUID(from_entity_uuid),
                    to_entity_type=to_entity_type,
                    to_entity_uuid=uuid.UUID(to_entity_uuid),
                    link_type=link_type,
                    created_by=created_by,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
