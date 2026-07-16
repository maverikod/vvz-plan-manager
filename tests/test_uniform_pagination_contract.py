"""Executable contract test for C-001 (UniformPagination): every retrofitted
large-output / runtime-entity-listing command exposes the identical
offset/limit input contract and documents total/limit/offset in its own
metadata(). Purely static: no database connection, no async execution.
branch_dump is exempt by ruling (file-based artifact served via export_read)
and is deliberately not enumerated here.
"""

from __future__ import annotations

import json

import pytest

from plan_manager.commands.runtime_filtering import pagination_schema_properties

from plan_manager.commands.block_list_command import BlockListCommand
from plan_manager.commands.bug_propagation_list_command import BugPropagationListCommand
from plan_manager.commands.concept_list_command import ConceptListCommand
from plan_manager.commands.execution_attempt_list_command import ExecutionAttemptListCommand
from plan_manager.commands.graph_order_command import GraphOrderCommand
from plan_manager.commands.graph_parallel_map_command import GraphParallelMapCommand
from plan_manager.commands.model_binding_list_command import ModelBindingListCommand
from plan_manager.commands.para_list_command import ParaListCommand
from plan_manager.commands.plan_list_command import PlanListCommand
from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand
from plan_manager.commands.project_dependency_list_command import ProjectDependencyListCommand
from plan_manager.commands.relation_list_command import RelationListCommand
from plan_manager.commands.review_result_list_command import ReviewResultListCommand
from plan_manager.commands.srt_snapshot_list_command import SrtSnapshotListCommand
from plan_manager.commands.step_runtime_list_command import StepRuntimeListCommand
from plan_manager.commands.step_tree_command import StepTreeCommand
from plan_manager.commands.todo_list_command import TodoListCommand
from plan_manager.commands.todo_queue_command import TodoQueueCommand

# Every command this CR retrofits (or, for todo_list, whose envelope shape
# this CR fixed) onto the uniform C-001 pagination contract.
_RETROFITTED_COMMANDS = [
    BlockListCommand,
    BugPropagationListCommand,
    ConceptListCommand,
    ExecutionAttemptListCommand,
    GraphOrderCommand,
    GraphParallelMapCommand,
    ModelBindingListCommand,
    ParaListCommand,
    PlanListCommand,
    PlanPromptChainCommand,
    ProjectDependencyListCommand,
    RelationListCommand,
    ReviewResultListCommand,
    SrtSnapshotListCommand,
    StepRuntimeListCommand,
    StepTreeCommand,
    TodoListCommand,
    TodoQueueCommand,
]

@pytest.mark.parametrize("command", _RETROFITTED_COMMANDS, ids=lambda c: c.name)
def test_schema_declares_uniform_pagination_properties(command) -> None:
    """Every retrofitted command's get_schema() properties for limit and offset
    are byte-for-byte identical to the shared pagination_schema_properties(),
    proving one uniform input contract across the whole command surface.
    """
    canonical = pagination_schema_properties()
    properties = command.get_schema()["properties"]
    assert "limit" in properties, f"{command.name}: schema missing 'limit' property"
    assert "offset" in properties, f"{command.name}: schema missing 'offset' property"
    assert properties["limit"] == canonical["limit"], f"{command.name}: limit schema diverges from canonical pagination_schema_properties()"
    assert properties["offset"] == canonical["offset"], f"{command.name}: offset schema diverges from canonical pagination_schema_properties()"

@pytest.mark.parametrize("command", _RETROFITTED_COMMANDS, ids=lambda c: c.name)
def test_metadata_documents_pagination_envelope(command) -> None:
    """Every retrofitted command's metadata() documents limit, offset, and total
    somewhere in its published metadata blob, so agents can discover the
    uniform page envelope without probing an INVALID_PAGINATION error first.
    """
    blob = json.dumps(command.metadata())
    for token in ("limit", "offset", "total"):
        assert token in blob, f"{command.name}: metadata() does not mention {token!r}"
