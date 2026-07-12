"""Contract tests for the 0.1.29 metadata-completeness campaign.

Every stateful entity's status vocabulary must be discoverable directly in the
metadata of at least one of its commands (not only via an INVALID_FILTER error),
and the info command's new agent_reference section must expose the exhaustive
answer key with a command index that exactly covers the normative inventory.
"""

from __future__ import annotations

import json

import pytest

from plan_manager.commands.bug_fix_list_command import BugFixListCommand
from plan_manager.commands.bug_impact_list_command import BugImpactListCommand
from plan_manager.commands.bug_list_command import BugListCommand
from plan_manager.commands.bug_propagation_list_command import BugPropagationListCommand
from plan_manager.commands.cascade_begin_command import CascadeBeginCommand
from plan_manager.commands.escalation_create_command import EscalationCreateCommand
from plan_manager.commands.execution_attempt_list_command import ExecutionAttemptListCommand
from plan_manager.commands.info_reference_agents import (
    _COMMAND_CATEGORIES,
    _QUEUED_COMMANDS,
    agent_reference,
)
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.review_result_list_command import ReviewResultListCommand
from plan_manager.commands.step_set_status_command import StepSetStatusCommand
from plan_manager.commands.todo_list_command import TodoListCommand
from plan_manager.domain.bug_fix import BugFixStatus
from plan_manager.domain.bug_fix_propagation import PropagationStatus
from plan_manager.domain.bug_impact import BugImpactStatus
from plan_manager.domain.bug_report import BugStatus
from plan_manager.domain.escalation import EscalationStatus
from plan_manager.domain.execution_attempt import ExecutionAttemptStatus
from plan_manager.domain.review_result import ReviewStatus
from plan_manager.domain.status_model import ATOMIC_ONLY_STATUSES, STATUSES
from plan_manager.domain.todo import TodoStatus


# Each stateful entity -> (a command whose metadata must publish the vocabulary,
# the ordered status values the entity actually enforces).
_STATUS_CONTRACT = {
    "bug": (BugListCommand, [e.value for e in BugStatus]),
    "bug_impact": (BugImpactListCommand, [e.value for e in BugImpactStatus]),
    "bug_fix": (BugFixListCommand, [e.value for e in BugFixStatus]),
    "bug_fix_propagation": (BugPropagationListCommand, [e.value for e in PropagationStatus]),
    "todo": (TodoListCommand, [e.value for e in TodoStatus]),
    "execution_attempt": (ExecutionAttemptListCommand, [e.value for e in ExecutionAttemptStatus]),
    "review_result": (ReviewResultListCommand, [e.value for e in ReviewStatus]),
    "escalation": (EscalationCreateCommand, [e.value for e in EscalationStatus]),
    "cascade": (CascadeBeginCommand, ["open", "committed", "aborted"]),
    "step": (StepSetStatusCommand, sorted(STATUSES | ATOMIC_ONLY_STATUSES)),
}


@pytest.mark.parametrize("entity", sorted(_STATUS_CONTRACT))
def test_status_vocabulary_published_in_command_metadata(entity: str) -> None:
    command, values = _STATUS_CONTRACT[entity]
    blob = json.dumps(command.metadata())
    missing = [value for value in values if value not in blob]
    assert not missing, f"{entity}: status values absent from {command.__name__}.metadata(): {missing}"


def test_agent_reference_status_vocabularies_cover_every_entity() -> None:
    vocab = agent_reference()["status_vocabularies"]["entities"]
    for entity, (_command, values) in _STATUS_CONTRACT.items():
        if entity == "step":
            published = vocab["step"]["values"]
        else:
            published = vocab[entity].get("values") or vocab[entity].get("confidence_levels")
        assert published is not None, f"{entity} missing from status_vocabularies"
        assert set(values).issubset(set(published)), f"{entity}: {set(values) - set(published)}"


def test_agent_reference_exposes_all_subsections() -> None:
    ref = agent_reference()
    assert set(ref) == {
        "status_vocabularies",
        "lifecycle_matrices",
        "operational_checklists",
        "anchor_types",
        "visibility_modes",
        "queue_polling",
        "crud_matrix",
        "command_index",
    }
    # The whole section must be JSON serializable (info returns it over JSON-RPC).
    json.dumps(ref)


def test_command_index_covers_inventory_exactly() -> None:
    indexed: list[str] = []
    for names in _COMMAND_CATEGORIES.values():
        indexed.extend(names)
    assert len(indexed) == len(set(indexed)), "a command is listed in more than one category"
    assert set(indexed) == set(INVENTORY), (
        f"missing={sorted(set(INVENTORY) - set(indexed))} "
        f"extra={sorted(set(indexed) - set(INVENTORY))}"
    )


def test_queue_polling_guide_lists_only_real_queued_commands() -> None:
    guide = agent_reference()["queue_polling"]
    assert guide["poll_command"] == "queue_get_job_status"
    assert set(guide["queued_commands"]) == set(_QUEUED_COMMANDS)
    assert _QUEUED_COMMANDS.issubset(set(INVENTORY))


def test_bug_lifecycle_documents_unreachable_statuses_honestly() -> None:
    bug = agent_reference()["lifecycle_matrices"]["bug"]
    assert bug["enforced"] is False
    # These BugStatus values are settable only at creation, never advanced by a command.
    for value in ("fixing", "fixed_source", "propagating", "verified"):
        assert value in bug["unreachable_post_creation"]
