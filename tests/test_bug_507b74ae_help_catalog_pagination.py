"""Regression tests for bug 507b74ae: help() with no cmdname returned an
unpaginated command catalog (~200+ commands on this server -- name + one-line
description per row) that exceeds agent/MCP response limits.

The plan_manager override of the platform 'help' builtin
(plan_manager.commands.help_command.HelpCommand, registered by
plan_manager.hooks.register_help_override -- same override pattern already
used for the 'health' builtin) now paginates the no-cmdname catalog with the
SAME uniform limit/offset contract used elsewhere in this project
(plan_manager.commands.runtime_filtering: bounded default 50, max 200).
help(cmdname=...) detail output is delegated to the builtin unchanged, per
the binding design decision that it stays exactly as-is.
"""

from __future__ import annotations

import asyncio

import mcp_proxy_adapter.commands.help_command as builtin_help_module
from mcp_proxy_adapter.commands.help_command import HelpCommand as BuiltinHelp

from plan_manager.commands import help_command as help_override
from plan_manager.commands.help_command import HelpCommand
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import check_inventory, register_all
from plan_manager.commands.runtime_filtering import pagination_schema_properties
from plan_manager.hooks import register_help_override


class FakeRegistry:
    def __init__(self) -> None:
        self.commands: dict = {}
        self._command_types: dict = {}

    def register(self, command_class, command_type: str = "builtin") -> None:
        self.commands[command_class.name] = command_class
        self._command_types[command_class.name] = command_type

    def get_all_commands(self) -> dict:
        return dict(self.commands)


def _synthetic_catalog(n: int) -> dict:
    return {
        f"cmd_{i:04d}": {
            "metadata": {"summary": f"One-line description of synthetic command {i:04d}."},
            "schema": {},
        }
        for i in range(n)
    }


def _patch_catalog(monkeypatch, n: int) -> None:
    monkeypatch.setattr(
        builtin_help_module.registry,
        "get_all_commands_info",
        lambda: {"commands": _synthetic_catalog(n)},
    )


def test_override_wins_and_stays_out_of_inventory() -> None:
    registry = FakeRegistry()
    registry.register(BuiltinHelp, "builtin")  # platform registers builtin first
    register_all(registry)
    register_help_override(registry)

    # The override replaces the builtin under the same name.
    assert registry.commands["help"] is help_override.HelpCommand
    assert registry._command_types["help"] == "builtin"
    # help is a platform override, never a member of the domain inventory.
    assert "help" not in INVENTORY
    # inventory invariants still hold with the override present.
    check_inventory(registry)


def test_schema_declares_uniform_pagination_properties_and_keeps_cmdname():
    properties = HelpCommand.get_schema()["properties"]
    canonical = pagination_schema_properties()
    assert properties["limit"] == canonical["limit"]
    assert properties["offset"] == canonical["offset"]
    assert "cmdname" in properties


def test_small_catalog_is_byte_compatible_beyond_the_new_pagination_key(monkeypatch):
    """A catalog within the default page size (50) returns every command, unchanged."""
    _patch_catalog(monkeypatch, 5)

    result = asyncio.run(HelpCommand().execute())
    data = result.to_dict()["data"]

    assert set(data["commands"]) == {f"cmd_{i:04d}" for i in range(5)}
    assert data["pagination"] == {
        "total": 5,
        "limit": 50,
        "offset": 0,
        "returned": 5,
        "has_more": False,
    }
    assert "tool_info" in data
    assert "help_usage" in data


def test_large_catalog_is_bounded_by_default_page_size(monkeypatch):
    """The observed defect: help() with no cmdname must never dump the whole
    ~200+ command catalog in one response."""
    _patch_catalog(monkeypatch, 250)

    result = asyncio.run(HelpCommand().execute())
    data = result.to_dict()["data"]

    assert len(data["commands"]) == 50  # DEFAULT_LIMIT, not the full 250
    assert data["pagination"]["total"] == 250
    assert data["pagination"]["limit"] == 50
    assert data["pagination"]["offset"] == 0
    assert data["pagination"]["has_more"] is True


def test_pagination_covers_every_command_alphabetically_with_no_duplicates_or_gaps(monkeypatch):
    _patch_catalog(monkeypatch, 120)

    seen: list[str] = []
    offset = 0
    while True:
        result = asyncio.run(HelpCommand().execute(limit=50, offset=offset))
        data = result.to_dict()["data"]
        seen.extend(data["commands"].keys())
        if not data["pagination"]["has_more"]:
            break
        offset += data["pagination"]["limit"]

    expected = sorted(f"cmd_{i:04d}" for i in range(120))
    assert seen == expected
    assert len(seen) == len(set(seen)) == 120


def test_explicit_limit_and_offset_slice_the_sorted_catalog(monkeypatch):
    _patch_catalog(monkeypatch, 10)

    result = asyncio.run(HelpCommand().execute(limit=3, offset=4))
    data = result.to_dict()["data"]

    assert list(data["commands"].keys()) == ["cmd_0004", "cmd_0005", "cmd_0006"]
    assert data["pagination"] == {
        "total": 10,
        "limit": 3,
        "offset": 4,
        "returned": 3,
        "has_more": True,
    }


def test_invalid_pagination_surfaces_invalid_pagination_domain_code(monkeypatch):
    _patch_catalog(monkeypatch, 5)

    result = asyncio.run(HelpCommand().execute(limit=0))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_cmdname_detail_path_is_delegated_unchanged(monkeypatch):
    """help(cmdname=...) is untouched by the pagination fix (binding L1 design)."""
    detail_payload = {
        "metadata": {"name": "plan_list", "summary": "List plans."},
        "schema": {"type": "object"},
    }
    monkeypatch.setattr(
        builtin_help_module.registry,
        "get_command_info",
        lambda name: detail_payload if name == "plan_list" else None,
    )

    result = asyncio.run(HelpCommand().execute(cmdname="plan_list"))
    data = result.to_dict()["data"]

    assert data == detail_payload
    assert "pagination" not in data


def test_row_is_bounded_defensively_even_for_a_pathologically_long_summary(monkeypatch):
    huge = "x" * 5000
    monkeypatch.setattr(
        builtin_help_module.registry,
        "get_all_commands_info",
        lambda: {"commands": {"weird_cmd": {"metadata": {"summary": huge}, "schema": {}}}},
    )

    result = asyncio.run(HelpCommand().execute())
    row = result.to_dict()["data"]["commands"]["weird_cmd"]

    assert len(row) <= 300
    assert row.endswith("…")
