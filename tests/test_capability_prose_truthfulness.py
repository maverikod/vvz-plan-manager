"""Guard against capabilities/agent_reference prose going stale relative to shipped code.

Scope note: a fully general "is this English sentence still true" checker is not
feasible. This module instead asserts a narrower, structural, cheap invariant
specifically for the DOMAIN_CODES set (plan_manager.commands.errors.DOMAIN_CODES):
no dict entry keyed by a DOMAIN_CODE, anywhere in the info command's capabilities
or agent_reference sections, may describe that code with "reserved" / "not
currently raised" / "not yet implemented" / "not yet supported" language while
some command's metadata()["error_cases"] actually advertises (wires) that same
code. This is a regression guard for the class of bug fixed 0.1.32/0.1.33:
DUPLICATE_LINK and LINK_CYCLE were wired by todo_link_add's typed guards but
plan_manager/commands/info_reference.py still described them as reserved/unraised.
"""

from __future__ import annotations

import re
from importlib import import_module
from typing import Any

from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.inventory import INVENTORY


_STALE_PHRASE_RE = re.compile(
    r"reserved|not currently raised|not yet implemented|not yet supported",
    re.IGNORECASE,
)


def _class_name(command_name: str) -> str:
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"


def _load_command_class(name: str):
    module = import_module(f"plan_manager.commands.{name}_command")
    return getattr(module, _class_name(name))


def _wired_domain_codes() -> set[str]:
    """Domain codes advertised (wired) by at least one command's error_cases."""
    wired: set[str] = set()
    for name in INVENTORY:
        cls = _load_command_class(name)
        error_cases = cls.metadata().get("error_cases", {})
        wired |= {code for code in error_cases if code in DOMAIN_CODES}
    return wired


def _find_domain_code_entries(obj: Any) -> list[tuple[str, str]]:
    """Recursively collect (domain_code, description) pairs for dict entries
    whose key is a DOMAIN_CODE and whose value is a description string."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in DOMAIN_CODES and isinstance(value, str):
                found.append((key, value))
            else:
                found.extend(_find_domain_code_entries(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_domain_code_entries(item))
    return found


def _no_db_info_sections() -> dict[str, Any]:
    """The subset of info()'s sections that need no database connection."""
    sections = (
        "capabilities",
        "agent_reference",
        "planning_standards",
        "mechanism_documentation",
        "delegation_method_documentation",
    )
    return {name: InfoCommand._section_data(name, {}) for name in sections}


def test_no_wired_domain_code_is_described_as_reserved_or_unraised() -> None:
    wired = _wired_domain_codes()
    assert wired, "sanity: expected at least one wired domain code from INVENTORY"

    sections = _no_db_info_sections()
    violations: list[str] = []
    for section_name, section_data in sections.items():
        for code, description in _find_domain_code_entries(section_data):
            if code in wired and _STALE_PHRASE_RE.search(description):
                violations.append(f"{section_name}: {code!r} -> {description!r}")

    assert not violations, (
        "stale 'reserved/not (currently) raised/not yet implemented' prose found "
        "for domain codes that are actually wired by a command's error_cases:\n"
        + "\n".join(violations)
    )


def test_domain_code_entries_exist_and_are_scanned() -> None:
    """Sanity check that the recursive walker actually finds domain_errors-shaped
    dicts in the live info() payload, so the guard above is not vacuously true."""
    sections = _no_db_info_sections()
    total = sum(len(_find_domain_code_entries(data)) for data in sections.values())
    assert total > 0, "no DOMAIN_CODE-keyed prose entries found; guard would be vacuous"


def test_export_delivery_subsection_present_in_capabilities_and_agent_reference() -> None:
    """Regression pin for CR-2 C-013: the export-delivery subsection added to the
    info command's capabilities and agent_reference sections must stay present and
    must not regress into stale reserved/not-yet-implemented domain-code prose."""
    sections = _no_db_info_sections()
    assert "export_delivery" in sections["capabilities"], (
        "info capabilities section must expose an 'export_delivery' subsection"
    )
    assert "export_delivery" in sections["agent_reference"], (
        "info agent_reference section must expose an 'export_delivery' subsection"
    )
    violations: list[str] = []
    for section_name in ("capabilities", "agent_reference"):
        subsection = sections[section_name]["export_delivery"]
        for code, description in _find_domain_code_entries(subsection):
            if _STALE_PHRASE_RE.search(description):
                violations.append(f"{section_name}.export_delivery: {code!r} -> {description!r}")
    assert not violations, (
        "stale domain-code prose found inside the export_delivery subsection:\n"
        + "\n".join(violations)
    )
