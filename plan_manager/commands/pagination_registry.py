"""Single registry of paginated command surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from plan_manager.commands.inventory import INVENTORY


@dataclass(frozen=True)
class PaginatedCommandSpec:
    """One command whose top-level surface accepts limit/offset pagination."""

    name: str
    uniform_fragment: bool = True


PAGINATED_COMMANDS: tuple[PaginatedCommandSpec, ...] = (
    PaginatedCommandSpec("audit_list"),
    PaginatedCommandSpec("block_get"),
    PaginatedCommandSpec("block_rebuild"),
    PaginatedCommandSpec("block_list"),
    PaginatedCommandSpec("bug_impact_list"),
    PaginatedCommandSpec("bug_fix_list"),
    PaginatedCommandSpec("bug_list"),
    PaginatedCommandSpec("bug_propagation_list"),
    PaginatedCommandSpec("calendar_entry_list"),
    PaginatedCommandSpec("command_catalog_dump", uniform_fragment=False),
    PaginatedCommandSpec("command_timing_stats"),
    PaginatedCommandSpec("comment_list"),
    PaginatedCommandSpec("concept_list"),
    PaginatedCommandSpec("context_bundle"),
    PaginatedCommandSpec("execution_attempt_list"),
    PaginatedCommandSpec("execution_dependency_suggest"),
    PaginatedCommandSpec("execution_graph"),
    PaginatedCommandSpec("escalation_list"),
    PaginatedCommandSpec("files_report"),
    PaginatedCommandSpec("graph_dependents"),
    PaginatedCommandSpec("graph_order"),
    PaginatedCommandSpec("graph_parallel_map"),
    PaginatedCommandSpec("invocation_profile_list"),
    PaginatedCommandSpec("model_binding_list"),
    PaginatedCommandSpec("model_list"),
    PaginatedCommandSpec("para_list"),
    PaginatedCommandSpec("plan_list"),
    PaginatedCommandSpec("plan_project_list"),
    PaginatedCommandSpec("plan_prompt_chain"),
    PaginatedCommandSpec("project_dependency_list"),
    PaginatedCommandSpec("provider_list"),
    PaginatedCommandSpec("relation_list"),
    PaginatedCommandSpec("review_result_list"),
    PaginatedCommandSpec("role_list"),
    PaginatedCommandSpec("runtime_link_list"),
    PaginatedCommandSpec("srt_snapshot_list"),
    PaginatedCommandSpec("step_dependency_list"),
    PaginatedCommandSpec("step_list"),
    PaginatedCommandSpec("step_runtime_list"),
    PaginatedCommandSpec("step_search"),
    PaginatedCommandSpec("step_tree"),
    PaginatedCommandSpec("step_xref"),
    PaginatedCommandSpec("todo_list"),
    PaginatedCommandSpec("todo_queue"),
    PaginatedCommandSpec("tool_list"),
    PaginatedCommandSpec("toolset_list"),
    PaginatedCommandSpec("wish_list"),
)

PAGINATED_COMMAND_NAMES: tuple[str, ...] = tuple(spec.name for spec in PAGINATED_COMMANDS)
UNIFORM_PAGINATED_COMMAND_NAMES: tuple[str, ...] = tuple(
    spec.name for spec in PAGINATED_COMMANDS if spec.uniform_fragment
)

INVENTORY_LIST_COMMANDS: tuple[str, ...] = tuple(sorted(name for name in INVENTORY if name.endswith("_list")))
