"""CR-3 scope boundary contract test (C-013): the group's four new read command modules exist and are non-mutating, no deploy-action command was added, the audit log has no write surface, and the gate's original twenty checks stay intact."""

from __future__ import annotations

from pathlib import Path

from plan_manager.commands.inventory import MUTATING
from plan_manager.verify.gate import CHECK_IDS, GROUP_ORDER

_REPO_ROOT = Path(__file__).resolve().parents[1]
_COMMANDS_DIR = _REPO_ROOT / "plan_manager" / "commands"

_NEW_READ_COMMAND_FILES = (
    "ops_status_command.py",
    "command_timing_stats_command.py",
    "step_prompt_verify_command.py",
    "audit_list_command.py",
)

_NEW_READ_COMMAND_NAMES = (
    "ops_status",
    "command_timing_stats",
    "step_prompt_verify",
    "audit_list",
)


def test_new_read_command_modules_exist() -> None:
    for filename in _NEW_READ_COMMAND_FILES:
        assert (_COMMANDS_DIR / filename).exists(), f"expected {filename} to exist"


def test_new_read_commands_are_non_mutating() -> None:
    for name in _NEW_READ_COMMAND_NAMES:
        assert name not in MUTATING, f"{name} must not be in MUTATING: CR-3 adds only read commands"


def test_no_deploy_action_command_module_exists() -> None:
    forbidden_substrings = ("deploy", "build_release", "cutover", "restart_service")
    command_files = list(_COMMANDS_DIR.glob("*_command.py"))
    offenders = []
    for file_path in command_files:
        filename = file_path.name
        for forbidden in forbidden_substrings:
            if forbidden in filename:
                offenders.append(filename)
                break
    assert not offenders, f"no deploy-action command module is allowed in CR-3; found: {offenders}"


def test_audit_log_has_no_companion_write_command_module() -> None:
    command_files = list(_COMMANDS_DIR.glob("*_command.py"))
    offenders = [
        file_path.name
        for file_path in command_files
        if file_path.name.startswith("audit_") and file_path.name != "audit_list_command.py"
    ]
    assert not offenders, f"audit_list must have no companion write command; found: {offenders}"


def test_mechanical_gate_original_twenty_checks_intact() -> None:
    original_groups = ("parse", "identity", "uniqueness", "references", "coverage")
    for group in original_groups:
        assert group in GROUP_ORDER, f"original gate group {group!r} missing from GROUP_ORDER"
        assert len(CHECK_IDS[group]) == 4, f"original gate group {group!r} must keep exactly 4 checks"
    total_original = sum(len(CHECK_IDS[group]) for group in original_groups)
    assert total_original == 20, "the five original gate check groups must total exactly 20 checks"
