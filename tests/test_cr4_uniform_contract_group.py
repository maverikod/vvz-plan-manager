"""Group-level contract test for CR-4 (C-009, C-010): the three commands into which CR-4's mutation-path mechanisms integrate stay registered as mutating commands, and no new top-level command is added by any of CR-4's four integration mechanisms."""

from __future__ import annotations

from plan_manager.commands.inventory import INVENTORY, MUTATING

_CR4_INTEGRATION_COMMANDS = ("step_create", "step_transition", "step_delete")

_CR4_MECHANISM_NAME_FRAGMENTS = (
    "context_coverage",
    "gate_check",
    "subtree_unfreeze",
    "subtree_delete",
    "delete_subtree",
    "recursive_delete",
    "membership_invariant",
    "context_block_admission",
)

# Inventory baseline WITHOUT any CR-4 addition: 153 pre-CR-4 commands plus the
# three paragraph text-editing commands (para_insert/para_update/para_delete)
# shipped by user-ordered phase-3 maintenance in 0.1.40 — those are not CR-4
# mechanisms (the fragment scan below guards against CR-4 mechanism commands).
_PRE_CR4_INVENTORY_COUNT = 156


def test_cr4_integration_commands_stay_mutating() -> None:
    for name in _CR4_INTEGRATION_COMMANDS:
        assert name in INVENTORY, f"{name} is not registered in the normative command inventory"
        assert name in MUTATING, f"{name} must stay a mutating command: CR-4 integrates into its existing mutation path"


def test_cr4_inventory_has_no_duplicate_entries() -> None:
    assert len(INVENTORY) == len(set(INVENTORY)), "INVENTORY must not contain duplicate entries"


def test_cr4_adds_no_new_top_level_command() -> None:
    assert len(INVENTORY) == _PRE_CR4_INVENTORY_COUNT, (
        f"CR-4 adds no new top-level command: every one of its four integration mechanisms "
        f"(admission guard, gate check group, subtree-unfreeze audit, recursive delete) is realized "
        f"inside an existing command; expected INVENTORY to still have exactly {_PRE_CR4_INVENTORY_COUNT} entries, "
        f"found {len(INVENTORY)}"
    )
    for fragment in _CR4_MECHANISM_NAME_FRAGMENTS:
        offenders = [name for name in INVENTORY if fragment in name]
        assert not offenders, f"found a command name containing {fragment!r}, suggesting a CR-4 mechanism was wrongly registered as a new command: {offenders}"
