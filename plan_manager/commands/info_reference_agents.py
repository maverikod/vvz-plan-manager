"""Exhaustive agent-facing reference data for the info command.

This module answers, without reading source, the questions an executing agent
most often has to reverse-engineer from code today: the full status vocabulary
of every stateful entity, the admissible status transitions and their
reachability caveats, the per-stage operational checklists for the multi-step
lifecycles, the anchor-type tables, comment visibility modes, the queue/polling
guide, the create/read/update/delete reality per entity, and a category index of
every command on the surface.

The tables themselves live in two sibling modules, split out for file-size
discipline (CR-1 C-014): info_reference_agents_status (status vocabularies and
lifecycle matrices) and info_reference_agents_catalog (operational checklists,
anchor types, visibility modes, queue polling, the pagination convention, the
CRUD matrix, and the command category index). This module stays the single stable public entry
point: agent_reference() (imported by info_command.py), plus
_COMMAND_CATEGORIES and _QUEUED_COMMANDS (imported by
tests/test_metadata_vocabulary_contract.py), are re-exported here unchanged so
existing imports keep working.
"""

from __future__ import annotations

from typing import Any

from plan_manager.commands.info_reference_agents_catalog import (
    _COMMAND_CATEGORIES,
    _QUEUED_COMMANDS,
    anchor_type_tables,
    command_index,
    crud_matrix,
    operational_checklists,
    pagination_convention_reference,
    queue_polling_guide,
    visibility_modes_reference,
)
from plan_manager.commands.info_reference_agents_status import (
    lifecycle_matrices,
    status_vocabularies,
)

__all__ = [
    "agent_reference",
    "status_vocabularies",
    "lifecycle_matrices",
    "operational_checklists",
    "anchor_type_tables",
    "visibility_modes_reference",
    "queue_polling_guide",
    "pagination_convention_reference",
    "crud_matrix",
    "command_index",
    "_COMMAND_CATEGORIES",
    "_QUEUED_COMMANDS",
]

def agent_reference() -> dict[str, Any]:
    """The full exhaustive agent-reference section returned by info."""
    return {
        "status_vocabularies": status_vocabularies(),
        "lifecycle_matrices": lifecycle_matrices(),
        "operational_checklists": operational_checklists(),
        "anchor_types": anchor_type_tables(),
        "visibility_modes": visibility_modes_reference(),
        "queue_polling": queue_polling_guide(),
        # Shipped wave-1 G-001 subsection restored per L1 ruling 2026-07-16
        # (guarded by tests/test_metadata_vocabulary_contract.py).
        "pagination_convention": pagination_convention_reference(),
        "crud_matrix": crud_matrix(),
        "command_index": command_index(),
    }
