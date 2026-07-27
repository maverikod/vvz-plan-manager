"""Contract tests for the single paginated-command registry."""

from __future__ import annotations

from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.pagination_registry import (
    INVENTORY_LIST_COMMANDS,
    PAGINATED_COMMAND_NAMES,
    UNIFORM_PAGINATED_COMMAND_NAMES,
)


def test_registry_has_no_duplicates() -> None:
    assert len(PAGINATED_COMMAND_NAMES) == len(set(PAGINATED_COMMAND_NAMES))


def test_every_inventory_list_command_is_registered_as_paginated() -> None:
    missing = sorted(set(INVENTORY_LIST_COMMANDS) - set(PAGINATED_COMMAND_NAMES))
    assert not missing, f"inventory list commands missing from pagination registry: {missing}"


def test_registry_only_mentions_live_inventory_commands() -> None:
    unknown = sorted(set(PAGINATED_COMMAND_NAMES) - set(INVENTORY))
    assert not unknown, f"pagination registry mentions unknown commands: {unknown}"


def test_uniform_registry_is_subset_of_full_registry() -> None:
    assert set(UNIFORM_PAGINATED_COMMAND_NAMES) <= set(PAGINATED_COMMAND_NAMES)


def test_known_non_list_paginated_surfaces_are_present() -> None:
    expected = {
        "block_get",
        "block_rebuild",
        "command_catalog_dump",
        "command_timing_stats",
        "context_bundle",
        "files_report",
        "graph_dependents",
        "graph_order",
        "graph_parallel_map",
        "plan_prompt_chain",
        "step_search",
        "step_tree",
        "step_xref",
    }
    assert expected <= set(PAGINATED_COMMAND_NAMES)
