"""Contract test for CR-1 obligation: every stateful entity that publishes a
status vocabulary also publishes a complete lifecycle transition-matrix entry
(C-016, DeliveryAcceptance).

Checked against the live plan_manager.commands.info_reference_agents module so
the test tracks the real agent-facing reference, not a copy of its data.
"""
from __future__ import annotations

from plan_manager.commands.info_reference_agents import (
    lifecycle_matrices,
    status_vocabularies,
)

def test_lifecycle_matrix_covers_every_status_vocabulary_entity() -> None:
    vocab_entities = set(status_vocabularies()["entities"])
    matrix_entities = set(lifecycle_matrices())
    missing_from_matrix = vocab_entities - matrix_entities
    extra_in_matrix = matrix_entities - vocab_entities
    assert not missing_from_matrix, (
        f"entities with a status vocabulary but no lifecycle matrix entry: {sorted(missing_from_matrix)}"
    )
    assert not extra_in_matrix, (
        f"lifecycle matrix entries with no corresponding status vocabulary entity: {sorted(extra_in_matrix)}"
    )

def test_every_lifecycle_matrix_entry_states_enforcement_and_notes() -> None:
    matrix = lifecycle_matrices()
    for entity, entry in matrix.items():
        assert isinstance(entry, dict), f"{entity}: lifecycle matrix entry must be a dict"
        assert "enforced" in entry, f"{entity}: lifecycle matrix entry missing 'enforced'"
        assert isinstance(entry["enforced"], bool), f"{entity}: 'enforced' must be a bool"
        assert "notes" in entry, f"{entity}: lifecycle matrix entry missing 'notes'"
        assert isinstance(entry["notes"], list), f"{entity}: 'notes' must be a list"
        assert len(entry["notes"]) > 0, f"{entity}: 'notes' must not be empty"
