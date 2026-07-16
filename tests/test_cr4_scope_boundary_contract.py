"""CR-4 scope boundary contract test (C-009): the group's named additive integrations land without a new deploy-action command, without a dedicated subtree-deletion command module, and with the original gate check groups fully intact."""

from __future__ import annotations

from pathlib import Path

from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.verify.gate import CHECK_IDS, GROUP_ORDER

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMMANDS_DIR = _REPO_ROOT / "plan_manager" / "commands"

_PRE_CR4_ORIGINAL_GROUPS = ("parse", "identity", "uniqueness", "references", "coverage")
_CR3_ADDITIVE_GROUP = "embedded_code"


def test_pre_cr4_gate_groups_intact() -> None:
    for group in _PRE_CR4_ORIGINAL_GROUPS:
        assert group in GROUP_ORDER, f"pre-CR-4 gate group {group!r} missing from GROUP_ORDER"
        assert len(CHECK_IDS[group]) == 4, f"pre-CR-4 gate group {group!r} must keep exactly 4 checks"
    assert _CR3_ADDITIVE_GROUP in GROUP_ORDER, "CR-3's embedded_code gate group must stay present"
    total_pre_cr4 = sum(len(CHECK_IDS[group]) for group in _PRE_CR4_ORIGINAL_GROUPS) + len(CHECK_IDS[_CR3_ADDITIVE_GROUP])
    assert total_pre_cr4 == 21, "the five original groups plus CR-3's embedded_code group must total exactly 21 pre-CR-4 checks"


def test_cr4_adds_exactly_one_new_gate_check_group() -> None:
    assert len(GROUP_ORDER) == 7, "CR-4 must add exactly one new gate check group beyond the CR-3 baseline of 6 (5 original + embedded_code)"
    baseline_groups = set(_PRE_CR4_ORIGINAL_GROUPS) | {_CR3_ADDITIVE_GROUP}
    new_groups = [group for group in GROUP_ORDER if group not in baseline_groups]
    assert len(new_groups) == 1, f"expected exactly one CR-4 gate check group, found: {new_groups}"
    new_group = new_groups[0]
    assert len(CHECK_IDS[new_group]) >= 1, f"CR-4 gate check group {new_group!r} must have at least one check"


def test_no_new_deploy_action_command_module_exists() -> None:
    forbidden_substrings = ("deploy", "build_release", "cutover", "restart_service")
    command_files = list(_COMMANDS_DIR.glob("*_command.py"))
    offenders = []
    for file_path in command_files:
        filename = file_path.name
        for forbidden in forbidden_substrings:
            if forbidden in filename:
                offenders.append(filename)
                break
    assert not offenders, f"no deploy-action command module is allowed in CR-4; found: {offenders}"


def test_no_dedicated_subtree_delete_command_module_exists() -> None:
    forbidden_substrings = ("subtree_delete", "delete_subtree", "recursive_delete")
    command_files = list(_COMMANDS_DIR.glob("*_command.py"))
    offenders = []
    for file_path in command_files:
        filename = file_path.name
        for forbidden in forbidden_substrings:
            if forbidden in filename:
                offenders.append(filename)
                break
    assert not offenders, f"CR-4 realizes recursive subtree deletion as a step_delete option, not a dedicated command module; found: {offenders}"
    assert "step_delete" in INVENTORY, "step_delete must remain registered in INVENTORY"
    assert "step_delete" in MUTATING, "step_delete must remain the single mutating deletion command"


def test_no_new_audit_write_command_module_exists() -> None:
    command_files = list(_COMMANDS_DIR.glob("*_command.py"))
    offenders = [
        file_path.name
        for file_path in command_files
        if file_path.name.startswith("audit_") and file_path.name != "audit_list_command.py"
    ]
    assert not offenders, f"audit_list must stay the sole audit-trail read command with no companion write command; found: {offenders}"
