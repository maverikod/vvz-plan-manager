"""Command: list generic runtime links, optionally filtered to one endpoint record, with uniform pagination (C-012, C-030)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.runtime_link_command_metadata import runtime_link_metadata
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    pagination_metadata_params,
    parse_pagination,
)
from plan_manager.domain.runtime_link import RUNTIME_LINK_ENTITY_TYPES
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_link_store import list_runtime_links


class RuntimeLinkListCommand(Command):
    name: ClassVar[str] = "runtime_link_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List generic runtime links, optionally filtered to one endpoint record, with uniform pagination."
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
                "entity_type": {
                    "type": "string",
                    "enum": sorted(RUNTIME_LINK_ENTITY_TYPES),
                    "description": "Entity type to filter by: bug or todo. Must be supplied together with entity_uuid.",
                },
                "entity_uuid": {
                    "type": "string",
                    "format": "uuid",
                    "description": "Entity UUID to filter by. Must be supplied together with entity_type.",
                },
                "include_deleted": {
                    "type": "boolean",
                    "description": "Include soft-deleted links. Defaults to false.",
                },
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)

        # Parse and validate entity_uuid if present
        if params.get("entity_uuid") is not None:
            try:
                uuid.UUID(params.get("entity_uuid"))
            except (ValueError, TypeError):
                raise DomainCommandError("INVALID_FILTER", f"entity_uuid must be a valid UUID, got {params.get('entity_uuid')!r}")

        # Enforce co-requirement: both must be supplied together or both must be absent
        entity_type_present = params.get("entity_type") is not None
        entity_uuid_present = params.get("entity_uuid") is not None

        if entity_type_present != entity_uuid_present:
            raise DomainCommandError("INVALID_FILTER", "entity_type and entity_uuid must be supplied together")

        return params

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {}
        parameters["entity_type"] = {
            "description": f"Entity type to filter by. One of: {', '.join(sorted(RUNTIME_LINK_ENTITY_TYPES))}. Must be supplied together with entity_uuid.",
            "type": "string",
            "required": False,
        }
        parameters["entity_uuid"] = {
            "description": "Entity UUID to filter by. Must be supplied together with entity_type.",
            "type": "string",
            "required": False,
        }
        parameters["include_deleted"] = {
            "description": "Include soft-deleted links. Defaults to false.",
            "type": "boolean",
            "required": False,
        }
        parameters.update(pagination_metadata_params())

        return_value = {
            "description": "An object with a runtime_links key holding a page of RuntimeLink records, plus total_count.",
            "type": "object",
        }

        examples = [
            {
                "description": "List all active links related to a specific bug.",
                "command": {
                    "entity_type": "bug",
                    "entity_uuid": "550e8400-e29b-41d4-a716-446655440000",
                    "limit": 50,
                },
            },
        ]

        return runtime_link_metadata(
            cls,
            parameters,
            return_value,
            examples,
            best_practices=[
                "Supply entity_type and entity_uuid together to filter to links touching one endpoint record; supplying only one of the two is rejected with INVALID_FILTER.",
                "Soft-deleted links are hidden by default; pass include_deleted=true to include them.",
                "Results are paginated with limit and offset (default limit 50, max 200); total_count reports the full number of matches before the page slice.",
                "The listing spans all four endpoint-kind pairs (bug-bug, bug-todo, todo-bug, todo-todo) and matches an endpoint on either the from or the to side.",
                "Links are returned ordered by created_at ascending.",
            ],
        )

    async def execute(
        self,
        entity_type: str | None = None,
        entity_uuid: str | None = None,
        include_deleted: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pg = parse_pagination({"limit": limit, "offset": offset})

            with db_connection() as conn:
                rows = list_runtime_links(
                    conn,
                    entity_type=entity_type,
                    entity_uuid=uuid.UUID(entity_uuid) if entity_uuid is not None else None,
                    include_deleted=bool(include_deleted) if include_deleted is not None else False,
                )

            payload = [r.to_payload() for r in rows]
            paged = payload[pg.offset : pg.offset + pg.limit]

            return SuccessResult(data={
                "runtime_links": paged,
                "total_count": len(payload),
            })
        except Exception as exc:
            return map_exception(exc)
