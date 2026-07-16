"""Contract test for CR-1 obligation: every command in the normative inventory is
reachable in the composed info command output (C-016, DeliveryAcceptance).

Checked against plan_manager.commands.info_reference_agents.agent_reference() —
the exact structure the info command returns to an agent — so a command that is
registered but never surfaced in info's command_index is caught. This is distinct
from tests/test_metadata_vocabulary_contract.py, which checks the module-private
_COMMAND_CATEGORIES dict; here we assert the delivery-facing composed surface.
"""
from __future__ import annotations

from plan_manager.commands.info_reference_agents import agent_reference
from plan_manager.commands.inventory import INVENTORY

def _reachable_command_names() -> set[str]:
    categories = agent_reference()["command_index"]["categories"]
    names: set[str] = set()
    for entries in categories.values():
        for entry in entries:
            names.add(entry["name"])
    return names

def test_info_command_index_reachable_in_agent_reference() -> None:
    ref = agent_reference()
    assert "command_index" in ref, "agent_reference() must expose a command_index"
    index = ref["command_index"]
    assert isinstance(index.get("categories"), dict), "command_index must expose a categories dict"

def test_every_inventory_command_reachable_in_info_command_index() -> None:
    reachable = _reachable_command_names()
    inventory = set(INVENTORY)
    missing = inventory - reachable
    extra = reachable - inventory
    assert not missing, f"inventory commands absent from info command_index: {sorted(missing)}"
    assert not extra, f"info command_index lists commands not in inventory: {sorted(extra)}"

def test_info_command_index_total_matches_inventory() -> None:
    index = agent_reference()["command_index"]
    assert index["total_commands"] == len(INVENTORY), (
        f"command_index total_commands {index['total_commands']} != len(INVENTORY) {len(INVENTORY)}"
    )
