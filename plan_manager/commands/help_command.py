"""Platform ``help`` command override: paginate the no-cmdname catalog.

Bug 507b74ae: the platform's builtin ``help`` command (adapter's
``mcp_proxy_adapter.commands.help_command.HelpCommand``), when called with no
``cmdname``, embeds a name -> one-line-description map for every registered
command (~200+ on this server) in a single response, exceeding agent/MCP
transport limits. ``help(cmdname=...)`` (detailed single-command output) is
unaffected -- it is a single command's payload, never the full catalog.

Fix: register a plan_manager override of ``help`` (same pattern already used
by ``health_command.py`` for the ``health`` builtin -- see
``plan_manager.hooks.register_health_override``) that adds ``limit``/
``offset`` pagination to the no-cmdname catalog, using the SAME uniform
pagination contract already shared by every paginated plan_manager command
(``plan_manager.commands.runtime_filtering``: bounded default 50, max 200
rows per page). The catalog is sorted alphabetically by command name for a
stable, deterministic page ordering across calls. ``cmdname=...`` detail
output is delegated to the builtin unchanged, per the binding design
decision that it stays exactly as-is. The existing envelope keys
(``tool_info``, ``help_usage``, ``commands``) are preserved so existing
callers reading those keys are unaffected; ``pagination`` is added
alongside. Each compact row is additionally bounded to ``_MAX_ROW_LEN``
characters as a defensive cap -- normally a no-op, since plan_manager
commands already carry a short one-line ``descr`` (see
``base_command.Command``), but it protects the bound even if a future
command's summary is accidentally long.

This override is not part of the normative plan_manager command inventory
(C-024): like the ``health`` override, it replaces a platform command rather
than adding a domain one, so it is registered directly against the registry
as a builtin replacement (``plan_manager.hooks.register_help_override``) and
is excluded from the inventory probe.
"""

from __future__ import annotations

from typing import Any, Optional

from mcp_proxy_adapter.commands.help_command import (
    HelpCommand as _BuiltinHelpCommand,
    HelpResult,
)

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    Pagination,
    pagination_schema_properties,
    parse_pagination,
)

_MAX_ROW_LEN = 300


def _truncate_row(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    if len(text) <= _MAX_ROW_LEN:
        return text
    return text[: _MAX_ROW_LEN - 1].rstrip() + "…"


class HelpCommand(_BuiltinHelpCommand):
    """Same as the builtin ``help``, except the no-cmdname catalog is paginated."""

    name = "help"

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        schema = dict(super().get_schema())
        properties = dict(schema.get("properties", {}))
        properties.update(pagination_schema_properties())
        schema["properties"] = properties
        schema["description"] = (
            "Get information about available commands. With cmdname: full "
            "detail for one command, unchanged. Without cmdname: a paginated "
            "compact catalog (name -> one-line description), bounded default "
            "50 rows, max 200 rows per page; see 'pagination' in the result "
            "for total/limit/offset."
        )
        return schema

    async def execute(self, cmdname: Optional[str] = None, **kwargs: Any) -> Any:
        if cmdname is not None and cmdname != "":
            return await super().execute(cmdname=cmdname, **kwargs)

        limit = kwargs.pop("limit", None)
        offset = kwargs.pop("offset", None)
        try:
            pagination: Pagination = parse_pagination({"limit": limit, "offset": offset})
        except Exception as exc:
            return map_exception(exc)

        base = await super().execute(cmdname=None, **kwargs)
        data = dict(base.commands_info or {})
        commands: dict[str, Any] = dict(data.get("commands") or {})

        sorted_names = sorted(commands.keys())
        total = len(sorted_names)
        page_names = sorted_names[pagination.offset : pagination.offset + pagination.limit]
        page_commands = {name: _truncate_row(commands[name]) for name in page_names}

        data["commands"] = page_commands
        data["pagination"] = {
            "total": total,
            "limit": pagination.limit,
            "offset": pagination.offset,
            "returned": len(page_commands),
            "has_more": (pagination.offset + len(page_commands)) < total,
        }
        return HelpResult(commands_info=data)
