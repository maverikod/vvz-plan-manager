"""Contract test for CR-1 obligation: the CRUD-matrix reference in the
agent-facing reference carries a complete four-operation entry for every
runtime entity mandated by the CRUD-with-integrity-deletion contract (C-016,
DeliveryAcceptance / C-008 CrudDeletionIntegrity).

The mandated entity list is the exact runtime-entity enumeration of the
CRUD-with-integrity-deletion contract: todo, todo_link, runtime_comment,
execution_attempt, review_result, escalation, model_binding, bug_report,
bug_impact, bug_fix, bug_fix_propagation, project_dependency, cascade_request.
The command-surface reference names two of these entities differently from
their domain module name: runtime_comment is published as "comment" and
bug_report is published as "bug" (both aliases confirmed against the domain
module names plan_manager.domain.runtime_comment and
plan_manager.domain.bug_report). The other eleven mandated names are used
verbatim as crud_matrix entity keys.
"""
from __future__ import annotations

from plan_manager.commands.info_reference_agents import crud_matrix

_MANDATED_ENTITIES: tuple[str, ...] = (
    "todo",
    "todo_link",
    "comment",  # alias of runtime_comment
    "execution_attempt",
    "review_result",
    "escalation",
    "model_binding",
    "bug",  # alias of bug_report
    "bug_impact",
    "bug_fix",
    "bug_fix_propagation",
    "project_dependency",
    "cascade_request",
)

_REQUIRED_OPERATIONS: tuple[str, ...] = ("create", "read", "update", "delete")

def test_crud_matrix_covers_every_mandated_entity() -> None:
    entities = crud_matrix()["entities"]
    missing = [name for name in _MANDATED_ENTITIES if name not in entities]
    assert not missing, f"CRUD matrix missing mandated entities: {missing}"

def test_crud_matrix_entries_state_all_four_operations() -> None:
    entities = crud_matrix()["entities"]
    for name in _MANDATED_ENTITIES:
        if name not in entities:
            continue
        entry = entities[name]
        for operation in _REQUIRED_OPERATIONS:
            assert operation in entry, f"{name}: CRUD matrix entry missing {operation!r}"
            assert isinstance(entry[operation], str) and entry[operation].strip(), (
                f"{name}: CRUD matrix {operation!r} must be a non-empty string"
            )
