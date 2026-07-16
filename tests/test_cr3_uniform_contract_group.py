"""Group-level contract test for CR-3 (C-011): every one of the five group deliverables that registers a command is present in the normative inventory as a non-mutating entry."""

from __future__ import annotations

from plan_manager.commands.inventory import INVENTORY, MUTATING

_CR3_REGISTERED_COMMANDS = ("ops_status", "command_timing_stats", "step_prompt_verify", "audit_list")


def test_cr3_deliverable_commands_are_registered_and_non_mutating() -> None:
    for name in _CR3_REGISTERED_COMMANDS:
        assert name in INVENTORY, f"{name} is not registered in the normative command inventory"
        assert name not in MUTATING, f"{name} must not be in MUTATING: it is a read-only command"


def test_cr3_inventory_has_no_duplicate_entries() -> None:
    assert len(INVENTORY) == len(set(INVENTORY)), "INVENTORY must not contain duplicate entries"
