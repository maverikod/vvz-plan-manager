"""Command: inspect the cross-entity reference graph around one entity (C-012).

Distinct from graph_dependents, which walks the step-dependency DAG. This command
walks the generic reference graph: which live rows, in any table, point at a given
entity. It answers "what would refuse a hard delete of this, and why" before the
deletion is attempted.

Module name note: the authoring step named this file
reference_inspection_command.py, but the registry derives a command's module from
its name (plan_manager.commands.<name>_command) and its class from the CamelCase
of that name. A file called reference_inspection_command.py would make
register_all raise "command inventory missing modules", so the convention wins.

Read-only: nothing here writes, and nothing here audits.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.hard_delete_guard import lookup_referrers
from plan_manager.storage.reference_catalog import (
    known_entity_types,
    table_name_for_entity_type,
)
from plan_manager.views.dependents_closure import DEFAULT_DEPTH_LIMIT, MAX_DEPTH_LIMIT


class ReferenceInspectCommand(Command):
    """Report the live rows that reference one entity, optionally transitively."""

    name: ClassVar[str] = "reference_inspect"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Inspect the cross-entity reference graph around one entity: which live rows "
        "point at it, optionally traversed transitively with cycle detection."
    )
    category: ClassVar[str] = "entity"
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
                    "description": (
                        "The user-facing entity type to inspect. This is the ENTITY_TYPE, "
                        "never the table name: 'todo', not 'todo_item'."
                    ),
                    "enum": known_entity_types(),
                },
                "entity_id": {
                    "type": "string",
                    "format": "uuid",
                    "description": "UUID of the entity to inspect.",
                },
                "recursive": {
                    "type": "boolean",
                    "description": (
                        "When true, follow referrers of referrers transitively, with cycle "
                        "detection and a depth bound."
                    ),
                    "default": False,
                },
                "depth_limit": {
                    "type": "integer",
                    "description": (
                        f"Maximum hops for a recursive traversal, clamped to "
                        f"[1, {MAX_DEPTH_LIMIT}]. Ignored when recursive is false."
                    ),
                    "minimum": 1,
                    "maximum": MAX_DEPTH_LIMIT,
                    "default": DEFAULT_DEPTH_LIMIT,
                },
                **pagination_schema_properties(),
            },
            "required": ["entity_type", "entity_id"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        entity_type: str,
        entity_id: str,
        recursive: bool = False,
        depth_limit: int = DEFAULT_DEPTH_LIMIT,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            origin_id = validate_uuid(entity_id)
            # Resolve to a TABLE NAME before touching the guard. For todo, bug,
            # comment and wish the ENTITY_TYPE differs from the table name, and
            # handing the entity type to lookup_referrers matches no catalog
            # entry and returns zero referrers — which reads as "nothing
            # references this" when in truth everything does (bugs e52daeab,
            # 113a7888). The shared helper is the only sanctioned conversion.
            origin_table = table_name_for_entity_type(entity_type)
            clamped_depth = _clamp_depth(depth_limit)

            with db_connection() as conn:
                direct = _serialize_referrers(lookup_referrers(conn, origin_table, origin_id))
                data: dict[str, Any] = {
                    "entity_type": entity_type,
                    "entity_id": str(origin_id),
                    "direct_referrers": direct,
                }
                if recursive:
                    items, traversal = _traverse(conn, origin_table, origin_id, clamped_depth)
                    data["traversal"] = traversal
                else:
                    items = direct

            total = len(items)
            window = items[pagination.offset : pagination.offset + pagination.limit]
            data.update(
                {
                    "items": window,
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                }
            )
            if recursive:
                data["traversal"]["total_count"] = total
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        return {
            "name": cls.name,
            "version": cls.version,
            "description": cls.descr,
            "category": cls.category,
            "author": cls.author,
            "email": cls.email,
            "detailed_description": (
                "Walks the generic cross-entity reference graph, which is a different graph "
                "from the one graph_dependents walks: that one follows declared step "
                "dependencies, this one follows real column references between rows of any "
                "two tables. The reported references are the ones that BLOCK a hard delete; "
                "a reference the database removes itself via ON DELETE CASCADE is not "
                "reported, because it refuses nothing. Read-only and audit-free."
            ),
            "parameters": {
                "entity_type": {
                    "type": "string",
                    "description": "The ENTITY_TYPE to inspect, never the table name.",
                    "required": True,
                    "enum": schema["properties"]["entity_type"]["enum"],
                },
                "entity_id": {
                    "type": "string",
                    "description": "UUID of the entity to inspect.",
                    "required": True,
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Follow referrers transitively when true.",
                    "required": False,
                },
                "depth_limit": {
                    "type": "integer",
                    "description": (
                        f"Hop bound for a recursive traversal, clamped to "
                        f"[1, {MAX_DEPTH_LIMIT}], default {DEFAULT_DEPTH_LIMIT}."
                    ),
                    "required": False,
                },
                **pagination_metadata_params(),
            },
            "return_value": {
                "success": {
                    "description": "The reference neighbourhood of the entity.",
                    "data": {
                        "entity_type": "The inspected entity type, echoed back.",
                        "entity_id": "The inspected entity id, echoed back.",
                        "direct_referrers": (
                            "One-hop referrers as {table, column, referrer_kind, referrer_id}. "
                            "The key is referrer_kind, matching the guard's lookup and the "
                            "DELETE_BLOCKED payload."
                        ),
                        "traversal": (
                            "Present only when recursive: {nodes_visited, edges_traversed, "
                            "cycles_detected, total_count}."
                        ),
                        "items": "The paginated referrer list (direct, or transitive when recursive).",
                        "total": "Full referrer count before pagination.",
                        "limit": "The applied limit.",
                        "offset": "The applied offset.",
                    },
                },
                "error": {
                    "description": "Domain error result on failure.",
                    "code": "Stable domain error code string (see error_cases).",
                    "message": "Human-readable error message.",
                },
            },
            "usage_examples": [
                {
                    "description": "See what directly references a todo before deleting it.",
                    "command": {
                        "entity_type": "todo",
                        "entity_id": "11111111-1111-1111-1111-111111111111",
                    },
                },
                {
                    "description": "Walk the whole blocking neighbourhood of a plan, three hops deep.",
                    "command": {
                        "entity_type": "plan",
                        "entity_id": "11111111-1111-1111-1111-111111111111",
                        "recursive": True,
                        "depth_limit": 3,
                    },
                },
            ],
            "error_cases": {
                "RUNTIME_VALIDATION_ERROR": {
                    "description": (
                        "entity_id is not a UUID, or entity_type names no known entity. The "
                        "schema enum rejects an unknown entity_type first in normal use."
                    ),
                    "message": "runtime validation failed: {details}",
                    "solution": (
                        "Pass an ENTITY_TYPE from the schema enum and a well-formed UUID; note "
                        "the type is 'todo', not the table name 'todo_item'."
                    ),
                },
                "INVALID_PAGINATION": {
                    "description": (
                        "limit or offset is not an integer, offset is negative, or limit is "
                        "outside the uniform pagination range."
                    ),
                    "message": "limit must be between 1 and {max}, got {value}",
                    "solution": "Correct limit/offset and retry.",
                },
            },
            "best_practices": [
                "Use the default one-hop form to answer 'why will this deletion be refused'. It "
                "is one SELECT per catalogued blocking column and cheap enough to call before "
                "every delete.",
                "Use recursive only to understand a subgraph you intend to dismantle. Cost grows "
                "with the neighbourhood, and every visited node costs another round of probes.",
                "Traversal is cycle-safe by construction: a node already visited is counted in "
                "cycles_detected and never expanded twice, so a mutual reference cannot loop.",
                "Tune depth_limit down rather than up. A depth of 2-3 answers most questions; the "
                f"clamp at {MAX_DEPTH_LIMIT} is a backstop, not a target.",
                "An empty result means nothing BLOCKS a hard delete. It does not mean nothing "
                "points at the entity: cascading references are removed by the database itself "
                "and are deliberately not reported here.",
            ],
        }


def _clamp_depth(depth_limit: Any) -> int:
    """Clamp a requested depth into the range the closure view declares."""
    if not isinstance(depth_limit, int) or isinstance(depth_limit, bool):
        return DEFAULT_DEPTH_LIMIT
    return max(1, min(depth_limit, MAX_DEPTH_LIMIT))


def _serialize_referrers(referrers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stringify identifiers so the payload is JSON-serializable."""
    return [
        {
            "table": referrer["table"],
            "column": referrer["column"],
            "referrer_kind": referrer["referrer_kind"],
            "referrer_id": str(referrer["referrer_id"]),
        }
        for referrer in referrers
    ]


def _traverse(
    conn: Any, origin_table: str, origin_id: Any, depth_limit: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Breadth-first walk of the blocking-reference graph, bounded and cycle-safe.

    Mirrors the frontier/visited shape of the dependents-closure view. The next
    hop reuses the referrer's own ``table`` value, which lookup_referrers already
    reports as a real table name; re-applying table_name_for_entity_type to it
    would raise, since 'todo_item' is a table name and not an entity type. The
    shared helper still owns the ONE conversion that matters — the caller-supplied
    entity_type at the origin.
    """
    visited: set[tuple[str, str]] = {(origin_table, str(origin_id))}
    frontier: list[tuple[str, Any]] = [(origin_table, origin_id)]
    collected: list[dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str, str]] = set()
    edges_traversed = 0
    cycles_detected = 0
    depth = 0

    while frontier and depth < depth_limit:
        next_frontier: list[tuple[str, Any]] = []
        for table, entity_id in frontier:
            for referrer in _serialize_referrers(lookup_referrers(conn, table, entity_id)):
                edge = (table, str(entity_id), referrer["table"], referrer["referrer_id"])
                if edge in seen_edges:
                    continue
                seen_edges.add(edge)
                edges_traversed += 1
                node = (referrer["table"], referrer["referrer_id"])
                if node in visited:
                    # Already expanded: counting it as a cycle rather than
                    # re-expanding is what makes a mutual reference terminate.
                    cycles_detected += 1
                    continue
                visited.add(node)
                collected.append({**referrer, "depth": depth + 1})
                next_frontier.append((referrer["table"], referrer["referrer_id"]))
        frontier = next_frontier
        depth += 1

    return collected, {
        "nodes_visited": len(visited),
        "edges_traversed": edges_traversed,
        "cycles_detected": cycles_detected,
        "total_count": len(collected),
    }
