"""Command: compile one common block and per-child specific deltas.

Bug 03956ccf: the compiled 'common' block (and each child's own delta block)
can grow to hundreds of entries when the parent scope is plan-wide (node
"plan" with no explicit shared_concepts pulls in every MRS concept), and the
uncapped 'content'/'blocks' list of such a block was returned in full,
exceeding agent response limits. Fixed the same way as block_get's own
per-block pagination (todo eb2dcccb): a single uniform limit/offset pair
(shared plan_manager.commands.runtime_filtering contract, bounded default 50,
max 200) is applied to the 'common' block's entry list and to every
'children[i]' entry's own entry list; each paginated block payload carries
'total'/'limit'/'offset' alongside the existing 'blocks'/'content' keys. A
bundle whose common and child blocks are all within the default page size
(the common case) is byte-compatible beyond these additive keys. A caller
that needs entries past the first page continues with
block_get(block_id, limit, offset) using the block_id already present in the
payload -- no semantic content changes, only the transport shape.

Bug a795ea4d: each child's specific block is now stored keyed additionally
by its supplied 'ref' (child_ref), so distinct children that happen to
share an identical concept scope -- and therefore compile a byte-identical,
possibly empty, delta -- each still get their own addressable, correctly-
attributed block_id instead of being silently aliased onto one shared row.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.context_block_metadata import BASE_PARAMETERS, context_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.runtime_filtering import (
    Pagination,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.views.context_blocks import (
    ContextRevision,
    common_context,
    resolve_context_revision,
    specific_delta,
    store_context_block,
)


def _paginate_block_payload(payload: dict[str, Any], pagination: Pagination) -> dict[str, Any]:
    """Return `payload` with its 'blocks'/'content' entry list bounded to one page.

    Mirrors block_get's per-block pagination contract exactly: the full entry
    list stays stored (this only bounds what is returned), 'total' is the
    unbounded entry count, and 'limit'/'offset' echo the applied page so a
    caller can detect and fetch further pages (via block_get, keyed by this
    payload's 'block_id').
    """
    entries = payload["content"]
    total = len(entries)
    page = entries[pagination.offset : pagination.offset + pagination.limit]
    paginated = dict(payload)
    paginated["blocks"] = list(page)
    paginated["content"] = list(page)
    paginated["total"] = total
    paginated["limit"] = pagination.limit
    paginated["offset"] = pagination.offset
    return paginated


class ContextBundleCommand(Command):
    name: ClassVar[str] = "context_bundle"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Compile a common context block and child-specific deltas."
    category: ClassVar[str] = "context"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
                "node": {"type": "string", "description": "Parent node: 'plan', a canonical step path, a step UUID, or an unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID."},
                "child_level": {"type": "integer", "description": "Level of children being authored: 3, 4, or 5."},
                "children": {"type": "array", "description": "Children array; each item has ref and concepts."},
                "shared_concepts": {"type": "array", "items": {"type": "string"}, "description": "Optional shared concept scope."},
                "revision": {"type": "string", "description": "Optional current head revision UUID."},
                "cascade_uuid": {"type": "string", "description": "Optional open cascade UUID."},
                **pagination_schema_properties(),
            },
            "required": ["plan", "node", "child_level", "children"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "node": {"description": "Parent node: 'plan', a canonical step path, a step UUID, or an unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.", "type": "string", "required": True},
            "child_level": {"description": "Level of children being authored: 3, 4, or 5.", "type": "integer", "required": True},
            "children": {"description": "Children array; each item has ref and concepts.", "type": "array", "required": True},
            "shared_concepts": {"description": "Optional common scope.", "type": "array", "required": False},
            **pagination_metadata_params(),
        }
        return context_metadata(
            cls,
            params,
            {
                "success": {
                    "description": (
                        "Bundle payload containing the stored common block and ordered "
                        "child delta blocks. The 'common' block and each 'children[i]' "
                        "entry carry only the current page of their own 'blocks'/'content' "
                        "entry list (bounded default 50, max 200 per page; the same "
                        "limit/offset pair applies to both), plus 'total'/'limit'/'offset' "
                        "describing that page. A block whose entry count is within the "
                        "default page size returns every entry in one call, unchanged from "
                        "before this parameter existed. Fetch further pages of a specific "
                        "block with block_get(block_id, limit, offset), using that block's "
                        "'block_id' ('common_block_id' for the common block)."
                    )
                }
            },
            [{"description": "Compile common and specific context for tactical children.", "command": {"plan": "plan_manager", "node": "G-002", "child_level": 4, "children": [{"ref": "session-core", "concepts": ["C-010"]}]}}],
            error_cases={
                "INVALID_PAGINATION": {
                    "description": "limit or offset is out of range or not an integer.",
                    "message": "limit must be between 1 and 200, got {limit}",
                    "solution": "Retry with limit in [1, 200] and offset >= 0.",
                },
            },
            extra_best_practices=[
                "A context_bundle response bounds each block's entry list to one page; "
                "compare offset+limit against total to detect further pages of the "
                "common block or of any child, then continue with block_get.",
                "A common block's entry count is typically small; only a plan-wide "
                "common scope (node 'plan' with no explicit shared_concepts) grows "
                "large enough to need a second page.",
            ],
        )

    async def execute(
        self,
        plan: str,
        node: str,
        child_level: int,
        children: list[dict[str, Any]],
        shared_concepts: list[str] | None = None,
        revision: str | None = None,
        cascade_uuid: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                context_revision = resolve_context_revision(conn, p, revision, cascade_uuid)
                node_path, scope, content = common_context(conn, p.uuid, node, child_level, shared_concepts)
                common = store_context_block(conn, p.uuid, context_revision, node_path, child_level, "common", scope, content)
                child_payloads = []
                inherited_revision = ContextRevision(common.revision_uuid, common.cascade_uuid)
                for index, child in enumerate(children):
                    child_scope, delta = specific_delta(conn, p.uuid, common, list(child.get("concepts", [])))
                    # Bug a795ea4d: without a per-child discriminator, siblings
                    # that share an identical concept scope compile a
                    # byte-identical (possibly empty) delta and would
                    # otherwise be silently aliased onto the same stored
                    # block by store_context_block's content-addressed dedup.
                    # child_ref threads each supplied child reference into
                    # that identity so every child gets its own addressable,
                    # correctly-attributed row; a caller that omits 'ref'
                    # still gets per-position distinctness within this call
                    # via the positional fallback.
                    child_ref = child.get("ref")
                    child_ref = str(child_ref) if child_ref is not None else f"__unnamed_child_{index}"
                    record = store_context_block(
                        conn,
                        p.uuid,
                        inherited_revision,
                        node_path,
                        child_level,
                        "specific",
                        child_scope,
                        delta,
                        common.block_id,
                        child_ref,
                    )
                    payload = _paginate_block_payload(record.to_payload(), pagination)
                    payload["ref"] = child.get("ref")
                    child_payloads.append(payload)
                common_payload = _paginate_block_payload(common.to_payload(), pagination)
                common_payload["common_block_id"] = common_payload["block_id"]
                return SuccessResult(data={"common": common_payload, "children": child_payloads})
        except Exception as exc:
            return map_exception(exc)
