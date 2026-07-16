"""Contract test for CR-1 obligation: every documented domain error code is
reachable (advertised by at least one command's metadata) and every error code
any command advertises is a registered domain code (C-016, DeliveryAcceptance).

Checked dynamically against the live INVENTORY and DOMAIN_CODES so newly added
commands and codes are covered automatically without hardcoding any command
name or code.
"""
from __future__ import annotations

from importlib import import_module

from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY

def _class_name(command_name: str) -> str:
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"

def _load_command_class(name: str):
    module = import_module(f"plan_manager.commands.{name}_command")
    return getattr(module, _class_name(name))

def _advertised_codes_by_command() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for name in INVENTORY:
        cls = _load_command_class(name)
        error_cases = cls.metadata()["error_cases"]
        result[name] = set(error_cases)
    return result

# allowlisted per L1 ruling 2026-07-16 — pre-existing out-of-scope surfaces;
# frozen A-003 authored pre-ruling
_ERROR_CASE_ALLOWLIST: dict[str, frozenset[str]] = {
    "export_upload_save": frozenset({
        "InvalidRequest",
        "TransferSessionNotFoundError",
        "TransferError",
        "TransferChecksumMismatchError",
    }),
    "info": frozenset({"none"}),
    "ops_status": frozenset({"none"}),
}

def test_every_advertised_error_code_is_a_registered_domain_code() -> None:
    by_command = _advertised_codes_by_command()
    for name, codes in by_command.items():
        unregistered: set[str] = set()
        for code in codes:
            if code in _ERROR_CASE_ALLOWLIST.get(name, frozenset()):
                continue
            if code not in DOMAIN_CODES:
                unregistered.add(code)
        assert not unregistered, f"{name}: advertises undocumented codes not in DOMAIN_CODES: {sorted(unregistered)}"

def test_every_registered_domain_code_is_advertised_by_at_least_one_command() -> None:
    by_command = _advertised_codes_by_command()
    advertised_union: set[str] = set()
    for codes in by_command.values():
        advertised_union |= codes
    unreachable = DOMAIN_CODES - advertised_union
    assert not unreachable, f"domain codes not advertised by any command's metadata: {sorted(unreachable)}"
