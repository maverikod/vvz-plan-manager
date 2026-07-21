"""Command: project-centric aggregate view of the runtime work registry (bug 18951d08).

The bug's original premise -- "project view hides anchored records" -- turned out to
be a feature gap, not a defect: plan_manager had no project-centric runtime read
surface at all; only the per-entity list commands (todo_list, bug_list, ...) accepted
an OPTIONAL project scope. This command is the missing surface, built strictly on top
of the existing, already-correct project-scoping machinery (list_todos_page /
list_bugs_page / list_comments_page's direct-OR-transitive-via-plan.project_ids SQL
predicate) -- it never reimplements that predicate, only calls it.

Equality-by-construction (the bug's own acceptance criterion): the todos/bugs UUID
sets and counters this command returns are produced by calling the exact same store
functions todo_list/bug_list call, with identical filter semantics (project, active_only).
A caller comparing project_view's todos/bugs against todo_list(project=..., active_only=...)
/ bug_list(project=..., active_only=...) under equal filters gets the same sets.

Scope note: only todo/bug/comment are covered. bug_impact, bug_fix, and
bug_fix_propagation are NOT covered in v1 -- see _OMITTED_KIND_REASONS below for why
each one's storage layer does not offer a trivial, drop-in project-filtered list call
matching this established pattern (assembling one would mean replicating command-layer
Python composition logic, not just calling one store function, which is out of scope
for this command).
"""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_command_metadata import runtime_metadata
from plan_manager.commands.runtime_filtering import MAX_LIMIT, parse_pagination
from plan_manager.domain.bug_report import BUG_STATUSES
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import list_bugs_page
from plan_manager.storage.runtime_comment_store import list_comments_page
from plan_manager.storage.todo_store import list_todos_page
from plan_manager.domain.todo import TODO_STATUSES

# Runtime record kinds with their own source/bug anchoring that are NOT covered by
# this command in v1, and the concrete reason each is excluded (checked against the
# actual storage-layer function signatures, not assumed):
_OMITTED_KIND_REASONS: dict[str, str] = {
    "bug_impact": (
        "storage_direct_only_no_transitive_parity: bug_impact_store.list_bug_impacts "
        "exposes target_project_id but only as a direct equality WHERE clause; the "
        "transitive plan.project_ids match bug_impact_list applies is command-layer "
        "Python composition (resolve_project_plan_uuids + post-fetch filtering), not "
        "a call this command could reuse without replicating that logic."
    ),
    "bug_fix": (
        "no_project_filter_surface: bug_fix_store.list_bug_fixes exposes no "
        "project_id-shaped parameter at all; bug_fix has a source_project_id column "
        "but project scoping for bug_fix_list is done entirely in command-layer "
        "Python via the parent bug's plan binding, not a store-level filter."
    ),
    "bug_fix_propagation": (
        "requires_precomputed_plan_uuid_list: bug_fix_propagation_store."
        "list_bug_fix_propagations accepts source_project_id and a transitive OR via "
        "an EXISTS join to the parent bug_fix/bug_report, but the caller must first "
        "resolve project_bound_plan_uuids itself (resolve_project_plan_uuids) and pass "
        "it in -- an extra composition step beyond a trivial, self-contained call."
    ),
}


def _fetch_all_rows(list_fn: Any, conn: Any, **kwargs: Any) -> tuple[list[Any], int]:
    """Fetch every row matching kwargs by paginating list_fn (a *_page store function)
    with MAX_LIMIT-sized pages, using ONLY that same store function -- no SQL of our
    own. Returns (all_rows, total). Bounded: offset strictly increases by MAX_LIMIT
    each iteration regardless of what pages come back, so this always terminates in
    ceil(total / MAX_LIMIT) iterations.
    """
    first_page, total = list_fn(conn, limit=MAX_LIMIT, offset=0, **kwargs)
    rows = list(first_page)
    offset = MAX_LIMIT
    while offset < total:
        page, _ = list_fn(conn, limit=MAX_LIMIT, offset=offset, **kwargs)
        rows.extend(page)
        offset += MAX_LIMIT
    return rows, total


def _status_counts(rows: list[Any], statuses: frozenset[str]) -> dict[str, int]:
    counts = {status: 0 for status in sorted(statuses)}
    for row in rows:
        if row.status in counts:
            counts[row.status] += 1
    return counts


class ProjectViewCommand(Command):
    name: ClassVar[str] = "project_view"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Project-centric aggregate view of the runtime work registry: todos, bugs, and comments scoped to one project, direct or transitive via bound plans."
    category: ClassVar[str] = "project_dependency"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "project": {"type": "string", "format": "uuid", "description": "External analysis-server project UUID to view (C-032)."},
                "active_only": {"type": "boolean", "description": "When true (the default), only active-status todos/bugs/unresolved comments are included in the page, summary, and diagnostics. Set false to include terminal-status records too."},
                "todo_limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Maximum todo rows to return in the todos page (default 50, max 200)."},
                "todo_offset": {"type": "integer", "minimum": 0, "description": "Todo rows to skip before the todos page (default 0)."},
                "bug_limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "description": "Maximum bug rows to return in the bugs page (default 50, max 200)."},
                "bug_offset": {"type": "integer", "minimum": 0, "description": "Bug rows to skip before the bugs page (default 0)."},
            },
            "required": ["project"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "project": {"description": "External analysis-server project UUID to view (C-032).", "type": "string", "required": True},
            "active_only": {"description": "When true (the default), only active-status todos/bugs/unresolved comments are included in the page, summary, and diagnostics. Set false to include terminal-status records too.", "type": "boolean", "required": False},
            "todo_limit": {"description": "Maximum todo rows to return in the todos page (default 50, max 200).", "type": "integer", "required": False},
            "todo_offset": {"description": "Todo rows to skip before the todos page (default 0).", "type": "integer", "required": False},
            "bug_limit": {"description": "Maximum bug rows to return in the bugs page (default 50, max 200).", "type": "integer", "required": False},
            "bug_offset": {"description": "Bug rows to skip before the bugs page (default 0).", "type": "integer", "required": False},
        }
        return runtime_metadata(
            cls,
            params,
            {"success": {"description": "project (uuid; no name -- planmgr never owns a local project catalog, C-032), summary (todo/bug status counts + totals), todos/bugs (independently paginated pages, each row annotated match_source: direct|transitive_plan), diagnostics (per-collection direct/transitive counts), and an additional comments section plus omitted_count_by_reason for the runtime record kinds not covered in v1."}},
            [{"description": "View a project's active work.", "command": {"project": "22222222-2222-2222-2222-222222222222", "active_only": True}}],
            best_practices=[
                "This command never reimplements the project-scope SQL predicate: it calls list_todos_page/list_bugs_page/list_comments_page -- the exact same store functions todo_list/bug_list/comment_list call -- with project and active_only as the only filters, so its todos/bugs UUID sets and counters match todo_list(project=..., active_only=...)/bug_list(project=..., active_only=...) exactly under equal filters.",
                "match_source on each todo/bug row is 'direct' when the row's own anchor_project_id/source_project_id equals the requested project, else 'transitive_plan' (reached only via the row's bound plan's plan.project_ids).",
                "summary and diagnostics are computed over the SAME active_only-filtered, project-scoped set as the todos/bugs pages -- not over the unfiltered universe; with the active_only default of true, terminal-status records (resolved/closed/cancelled todos, closed/rejected/duplicate bugs) contribute 0 to the status counts unless active_only=false is passed.",
                "No project name is returned: planmgr stores only an opaque external project UUID reference (C-032) and never owns or looks up a local project catalog, so there is nothing to resolve a name from.",
                "bug_impact, bug_fix, and bug_fix_propagation are NOT covered -- see omitted_count_by_reason for the concrete per-kind reason (each lacks a trivial, self-contained project-filtered store call matching this command's established direct-OR-transitive pattern).",
                "An unknown/nonexistent project UUID is a valid, empty view (all counts 0, empty pages) -- not an error, matching todo_list/bug_list/comment_list's own project-filter behavior.",
            ],
        )

    async def execute(
        self,
        project: str,
        active_only: bool | None = None,
        todo_limit: int | None = None,
        todo_offset: int | None = None,
        bug_limit: int | None = None,
        bug_offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                project_uuid = validate_uuid(project)
                active = True if active_only is None else bool(active_only)

                todo_pagination = parse_pagination({"limit": todo_limit, "offset": todo_offset})
                bug_pagination = parse_pagination({"limit": bug_limit, "offset": bug_offset})

                all_todos, todo_total = _fetch_all_rows(
                    list_todos_page, conn, project_id=project_uuid, active_only=active, include_deleted=False,
                )
                all_bugs, bug_total = _fetch_all_rows(
                    list_bugs_page, conn, project_id=project_uuid, active_only=active, include_deleted=False,
                )
                all_comments, comment_total = _fetch_all_rows(
                    list_comments_page, conn, project_id=project_uuid, active_only=active, include_deleted=False,
                )

                todo_direct = sum(1 for r in all_todos if r.anchor_project_id == project_uuid)
                bug_direct = sum(1 for r in all_bugs if r.source_project_id == project_uuid)
                comment_direct = sum(1 for r in all_comments if r.anchor_project_id == project_uuid)

                todo_page = all_todos[todo_pagination.offset:todo_pagination.offset + todo_pagination.limit]
                bug_page = all_bugs[bug_pagination.offset:bug_pagination.offset + bug_pagination.limit]

                todos_payload = [
                    {**r.to_payload(), "match_source": "direct" if r.anchor_project_id == project_uuid else "transitive_plan"}
                    for r in todo_page
                ]
                bugs_payload = [
                    {**r.to_payload(), "match_source": "direct" if r.source_project_id == project_uuid else "transitive_plan"}
                    for r in bug_page
                ]

                return SuccessResult(data={
                    "project": {"uuid": str(project_uuid)},
                    "summary": {
                        "todos": {**_status_counts(all_todos, TODO_STATUSES), "total": todo_total},
                        "bugs": {**_status_counts(all_bugs, BUG_STATUSES), "total": bug_total},
                    },
                    "todos": todos_payload,
                    "todo_total": todo_total,
                    "todo_limit": todo_pagination.limit,
                    "todo_offset": todo_pagination.offset,
                    "bugs": bugs_payload,
                    "bug_total": bug_total,
                    "bug_limit": bug_pagination.limit,
                    "bug_offset": bug_pagination.offset,
                    "diagnostics": {
                        "todos": {"direct_project_anchor_count": todo_direct, "transitive_plan_match_count": todo_total - todo_direct},
                        "bugs": {"direct_project_anchor_count": bug_direct, "transitive_plan_match_count": bug_total - bug_direct},
                        "comments": {"direct_project_anchor_count": comment_direct, "transitive_plan_match_count": comment_total - comment_direct},
                    },
                    "comments": {"total": comment_total},
                    "omitted_count_by_reason": dict(_OMITTED_KIND_REASONS),
                })
        except Exception as exc:
            return map_exception(exc)
