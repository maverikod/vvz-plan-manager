"""Command: dump the complete machine-readable command catalog (C-007), paginated (C-001).

Bug 85b180bf: called with no params this command previously returned the
entire ~200+ command catalog in one response. FIRST fix attempt (commit
8a3d6fc) bounded the default page to the shared runtime_filtering
DEFAULT_LIMIT (50 entries) and sorted entries deterministically by command
name (todo 9c409a47), but count-only bounding turned out NOT to close the
live defect: unlike every other paginated entity in this project (steps,
bugs, todos -- small structured records), each catalog entry embeds a
COMPLETE per-command metadata blob (full parameter descriptions/examples,
usage_examples, error_cases, best_practices) copied verbatim from that
command's own metadata(); measured against the real, live catalog (199
commands, 2026-07-24) these entries average ~4.3 KB each (min 0.8 KB, max
9.7 KB) -- so a "bounded to 50 entries" page still serialized to ~248 KB,
almost DOUBLE the original bug's own ~130 KB complaint. Count-based
pagination alone cannot make this command's DEFAULT response small: the
uniform runtime_filtering.DEFAULT_LIMIT (50) is sized for lightweight
entities, not this one.

REVISED fix: this command's own no-param default is _DEFAULT_CATALOG_LIMIT
(10 entries, ~48 KB on the real catalog -- a real, meaningful bound, well
under the original complaint) instead of the shared DEFAULT_LIMIT, while
`limit`/`offset` keep the exact same semantics, validation, and MAX_LIMIT
(200) as every other paginated command (parse_pagination is still the sole
validator; only the value substituted for an OMITTED limit differs, and
that substitution happens before parse_pagination ever runs, so
INVALID_PAGINATION and offset defaulting are completely unaffected). This
command is deliberately NOT part of the byte-for-byte
pagination_schema_properties() contract enforced by
tests/test_uniform_pagination_contract.py's _RETROFITTED_COMMANDS list, so
get_schema() overrides the `limit` property's description to state the
true default truthfully (bug-fix truthfulness: never document a stale
default). Sort-by-name (todo 9c409a47) and the additive `returned`/
`has_more` envelope keys from the first fix attempt are unchanged.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.command_catalog_dump_metadata import get_command_catalog_dump_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.views.command_catalog import build_command_catalog

# This command's own no-param default (bug 85b180bf revised fix). Smaller
# than the shared runtime_filtering.DEFAULT_LIMIT (50) because catalog
# entries are full per-command metadata blobs (~4.3 KB average on the live
# 199-command catalog, 2026-07-24), not lightweight structured records: 50
# of them still serialize to ~248 KB, which does not actually bound the
# response. 10 entries land at ~48 KB on the real catalog -- a genuine
# bound, comfortably under the original bug's ~130 KB complaint. Still just
# the substituted value for an OMITTED `limit`; parse_pagination's own
# validation range (1..MAX_LIMIT) and INVALID_PAGINATION behavior for an
# explicitly-provided out-of-range limit are completely unchanged.
_DEFAULT_CATALOG_LIMIT: int = 10

class CommandCatalogDumpCommand(Command):
    name: ClassVar[str] = "command_catalog_dump"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return the complete machine-readable command catalog, generated from the live command inventory."
    category: ClassVar[str] = "system"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        properties = dict(pagination_schema_properties())
        # Truthfully document the smaller, command-specific no-param
        # default (see _DEFAULT_CATALOG_LIMIT docstring above); max and
        # validation semantics stay identical to the shared contract.
        limit_property = dict(properties["limit"])
        limit_property["description"] = (
            "Maximum number of catalog entries to return (default "
            f"{_DEFAULT_CATALOG_LIMIT} for this command specifically -- "
            "smaller than the project's general 50-row default because "
            "each entry is a complete per-command metadata blob; max 200, "
            "same as every other paginated command)."
        )
        properties["limit"] = limit_property
        return {
            "type": "object",
            "properties": properties,
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_command_catalog_dump_metadata(cls)

    async def execute(
        self,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            effective_limit = limit if limit is not None else _DEFAULT_CATALOG_LIMIT
            pagination = parse_pagination({"limit": effective_limit, "offset": offset})
            entries = sorted(build_command_catalog(), key=lambda entry: entry["name"])
            total = len(entries)
            page = entries[pagination.offset : pagination.offset + pagination.limit]
            returned = len(page)
            return SuccessResult(data={
                "commands": page,
                "total": total,
                "limit": pagination.limit,
                "offset": pagination.offset,
                "returned": returned,
                "has_more": (pagination.offset + returned) < total,
            })
        except Exception as exc:
            return map_exception(exc)
