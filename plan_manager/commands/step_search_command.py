"""Command: search step content for an exact substring or a regular expression,
scoped to a plan or one branch (step_search)."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import parse_pagination
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.commands.step_search_metadata import get_step_search_metadata
from plan_manager.commands.step_search_schema import MAX_PATTERN_LENGTH, get_step_search_schema
from plan_manager.runtime.context import db_connection
from plan_manager.views.branch import resolve_branch
from plan_manager.views.dependency_graph import load_steps


CONTEXT_RADIUS: int = 40

_LEVEL_TEXT_FIELDS: dict[int, tuple[str, ...]] = {
    3: ("name", "description"),
    4: ("name", "description"),
    5: ("name", "target_file", "prompt"),
}


def _field_texts(level: int, fields: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (field_name, text) pairs for every non-empty searchable text field of a step."""
    result: list[tuple[str, str]] = []
    for field_name in _LEVEL_TEXT_FIELDS.get(level, ()):
        text = fields.get(field_name)
        if isinstance(text, str) and text:
            result.append((field_name, text))
    return result


def _excerpt(text: str, start: int, end: int) -> str:
    """Return a bounded context excerpt of text around the [start, end) match span."""
    left = max(0, start - CONTEXT_RADIUS)
    right = min(len(text), end + CONTEXT_RADIUS)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}"


def _find_matches(mode: str, pattern: str, text: str) -> list[tuple[int, int]]:
    """Return every non-overlapping (start, end) match span of pattern in text."""
    spans: list[tuple[int, int]] = []
    if mode == "regex":
        compiled = re.compile(pattern)
        for match in compiled.finditer(text):
            spans.append((match.start(), match.end()))
        return spans
    start = 0
    while True:
        idx = text.find(pattern, start)
        if idx == -1:
            break
        end = idx + len(pattern)
        spans.append((idx, end))
        start = idx + max(len(pattern), 1)
    return spans


class StepSearchCommand(Command):
    """Search step content for an exact substring or a regular expression, scoped to a plan or one branch."""

    name: ClassVar[str] = "step_search"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Search step content for an exact substring or regex, scoped to a plan or one branch."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for step_search."""
        return get_step_search_schema()

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for step_search."""
        return get_step_search_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate step_search parameters.

        Note:
            A malformed regex pattern, an over-length pattern, or an
            inconsistent scope/step-id combination is NOT converted to a
            domain error here: a bare ValueError raised from validate_params
            is wrapped by the adapter into a generic -32603 InternalError.
            execute() re-validates the same conditions instead, so each one
            surfaces as a clean INVALID_FILTER domain code.
        """
        params = super().validate_params(params)
        pattern = params.get("pattern")
        mode = params.get("mode", "substring")
        if isinstance(pattern, str):
            if len(pattern) > MAX_PATTERN_LENGTH:
                raise ValueError(
                    f"pattern must be at most {MAX_PATTERN_LENGTH} characters, got {len(pattern)}"
                )
            if mode == "regex":
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise ValueError(f"invalid regular expression: {exc}") from exc
        scope = params.get("scope", "plan")
        gs_step_id = params.get("gs_step_id")
        ts_step_id = params.get("ts_step_id")
        as_step_id = params.get("as_step_id")
        if scope == "branch":
            if not (gs_step_id and ts_step_id and as_step_id):
                raise ValueError("scope 'branch' requires gs_step_id, ts_step_id, and as_step_id")
        elif gs_step_id or ts_step_id or as_step_id:
            raise ValueError("scope 'plan' must not receive gs_step_id, ts_step_id, or as_step_id")
        return params

    async def execute(
        self,
        plan: str,
        pattern: str,
        mode: str = "substring",
        scope: str = "plan",
        gs_step_id: str | None = None,
        ts_step_id: str | None = None,
        as_step_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Search step content for an exact substring or a regular expression.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            pattern: Substring or regular expression to search for.
            mode: "substring" for exact matching, or "regex" for regular-expression matching.
            scope: "plan" to search the whole plan, or "branch" to search one branch.
            gs_step_id: Global step id of the branch; required when scope is "branch".
            ts_step_id: Tactical step id of the branch; required when scope is "branch".
            as_step_id: Atomic step id of the branch; required when scope is "branch".
            limit: Maximum number of matches to return (default 50, max 200).
            offset: Number of matches to skip before returning results (default 0).

        Returns:
            SuccessResult with data {"matches": [...], "total_count": int}, where
            each match entry has "path", "field", "excerpt", or ErrorResult with
            code PLAN_NOT_FOUND, STEP_NOT_FOUND, INVALID_FILTER, or
            INVALID_PAGINATION.
        """
        try:
            if len(pattern) > MAX_PATTERN_LENGTH:
                raise DomainCommandError(
                    "INVALID_FILTER",
                    f"pattern must be at most {MAX_PATTERN_LENGTH} characters, got {len(pattern)}",
                )
            if scope == "branch":
                if not (gs_step_id and ts_step_id and as_step_id):
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        "scope 'branch' requires gs_step_id, ts_step_id, and as_step_id",
                    )
            elif gs_step_id or ts_step_id or as_step_id:
                raise DomainCommandError(
                    "INVALID_FILTER",
                    "scope 'plan' must not receive gs_step_id, ts_step_id, or as_step_id",
                )
            if mode == "regex":
                try:
                    re.compile(pattern)
                except re.error as exc:
                    raise DomainCommandError("INVALID_FILTER", f"invalid regular expression: {exc}") from exc
            pagination = parse_pagination({"limit": limit, "offset": offset})
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                nodes = load_steps(conn, p.uuid)
                if scope == "branch":
                    try:
                        branch = resolve_branch(conn, p.uuid, gs_step_id, ts_step_id, as_step_id)
                    except ValueError as exc:
                        return domain_error("STEP_NOT_FOUND", str(exc))
                    candidates = [branch.gs, branch.ts, branch.atomic]
                else:
                    candidates = list(nodes.values())
                matches: list[dict[str, Any]] = []
                for step in candidates:
                    for field_name, text in _field_texts(step.level, step.fields):
                        for start, end in _find_matches(mode, pattern, text):
                            matches.append({
                                "path": canonical_step_path(nodes, step),
                                "field": field_name,
                                "excerpt": _excerpt(text, start, end),
                            })
                total_count = len(matches)
                page = matches[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={"matches": page, "total_count": total_count})
        except Exception as exc:
            return map_exception(exc)
