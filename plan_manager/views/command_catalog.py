"""Computed command catalog view: derives the machine-readable command catalog
from the live command inventory (C-007 CommandCatalog).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from plan_manager.commands.inventory import INVENTORY

def _class_name(command_name: str) -> str:
    """Return the CamelCase command class name for a bare inventory command name.

    :param command_name: Bare inventory command name (e.g. "command_catalog_dump").
    :type command_name: str
    :return: The class name the command module defines (e.g. "CommandCatalogDumpCommand").
    :rtype: str
    """
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"

def build_command_catalog() -> list[dict[str, Any]]:
    """Build the complete machine-readable command catalog from the live inventory.

    Iterates plan_manager.commands.inventory.INVENTORY in order and, for each
    bare command name, imports its command module
    (plan_manager.commands.<name>_command), resolves its command class via
    _class_name, and reads that class's own metadata() classmethod and
    use_queue ClassVar to build one catalog entry. The catalog is generated
    from the live command inventory as the single source of truth; it is
    never hand-maintained.

    :return: One dict per INVENTORY command, in INVENTORY order, each with
        exactly the keys "name" (str, the bare inventory command name),
        "category" (str, the command class's category ClassVar),
        "parameters" (dict, the command's metadata()["parameters"]),
        "execution_mode" (str: "queued" when the class's use_queue ClassVar
        is True, else "direct"), "metadata" (dict with keys "description",
        "error_cases", "best_practices", "usage_examples" taken from the
        command's metadata()), and "source_module" (str, the dotted module
        path "plan_manager.commands.<name>_command").
    :rtype: list[dict[str, Any]]
    """
    entries: list[dict[str, Any]] = []
    for name in INVENTORY:
        module_name = f"plan_manager.commands.{name}_command"
        module = import_module(module_name)
        cls = getattr(module, _class_name(name))
        meta = cls.metadata()
        entries.append({
            "name": name,
            "category": cls.category,
            "parameters": meta.get("parameters", {}),
            "execution_mode": "queued" if getattr(cls, "use_queue", False) else "direct",
            "metadata": {
                "description": meta.get("description"),
                "error_cases": meta.get("error_cases"),
                "best_practices": meta.get("best_practices"),
                "usage_examples": meta.get("usage_examples"),
            },
            "source_module": module_name,
        })
    return entries
