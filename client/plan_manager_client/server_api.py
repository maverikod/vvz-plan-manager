"""Canonical plan_manager command-set and facade-completeness assertions.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

import inspect
from typing import Iterable
from typing import Type

COMMAND_NAMES: frozenset[str] = frozenset(
    (
        "plan_create",
        "plan_list",
        "plan_status",
        "plan_delete",
        "plan_project_attach",
        "plan_project_detach",
        "plan_project_list",
        "plan_project_set_primary",
        "plan_project_clear_primary",
        "plan_export",
        "plan_snapshot",
        "plan_import",
        "export_upload_save",
        "export_read",
        "export_archive",
        "hrs_import",
        "hrs_export",
        "export_cleanup",
        "para_list",
        "para_get",
        "para_label_assign",
        "para_mark_non_binding",
        "concept_get",
        "concept_list",
        "concept_add",
        "concept_update",
        "concept_remove",
        "relation_list",
        "relation_add",
        "relation_update",
        "relation_remove",
        "concept_coverage",
        "step_get",
        "step_tree",
        "step_create",
        "step_update",
        "step_move",
        "step_delete",
        "step_set_status",
        "step_transition",
        "step_runtime_get",
        "step_runtime_report",
        "step_runtime_list",
        "step_list",
        "step_search",
        "files_report",
        "step_xref",
        "graph_deps",
        "graph_order",
        "graph_parallel_map",
        "graph_impact",
        "step_dependency_list",
        "step_dependency_add",
        "step_dependency_remove",
        "step_dependency_set",
        "step_dependency_clear",
        "step_dependency_preview",
        "step_dependency_apply",
        "branch_prompt",
        "plan_prompt_chain",
        "context_compile",
        "context_common",
        "context_specific",
        "context_bundle",
        "block_get",
        "block_list",
        "branch_dump",
        "branch_weak",
        "plan_validate",
        "plan_score",
        "cascade_begin",
        "cascade_preview",
        "cascade_commit",
        "cascade_abort",
        "plan_unfreeze",
        "srt_snapshot_create",
        "srt_snapshot_list",
        "srt_diff",
        "info",
        "todo_create",
        "todo_get",
        "todo_list",
        "todo_update",
        "todo_reanchor",
        "todo_resolve",
        "todo_close",
        "todo_delete",
        "todo_link_add",
        "todo_link_remove",
        "todo_queue",
        "todo_promote_to_cascade_request",
        "runtime_link_add",
        "runtime_link_list",
        "runtime_link_remove",
        "comment_add",
        "comment_get",
        "comment_list",
        "comment_supersede",
        "comment_resolve",
        "comment_delete",
        "model_binding_set",
        "model_binding_get",
        "model_binding_list",
        "model_binding_update",
        "model_binding_remove",
        "model_binding_resolve",
        "execution_attempt_create",
        "execution_attempt_report",
        "execution_attempt_get",
        "execution_attempt_list",
        "review_result_create",
        "review_result_get",
        "review_result_list",
        "escalation_create",
        "escalation_get",
        "escalation_list",
        "escalation_resolve",
        "bug_create",
        "bug_get",
        "bug_list",
        "bug_update",
        "bug_reanchor",
        "bug_triage",
        "bug_confirm",
        "bug_reject",
        "bug_mark_duplicate",
        "bug_reopen",
        "bug_close",
        "bug_impact_add",
        "bug_impact_update",
        "bug_impact_list",
        "bug_impact_discover",
        "bug_fix_create",
        "bug_fix_update",
        "bug_fix_list",
        "bug_fix_verify",
        "bug_propagation_create",
        "bug_propagation_list",
        "bug_propagation_update",
        "bug_propagation_generate_todos",
        "project_dependency_add",
        "project_dependency_update",
        "project_dependency_confirm",
        "project_dependency_remove",
        "project_dependency_list",
        "project_dependency_discover",
        "project_dependents",
        "command_catalog_dump",
        "graph_dependents",
        "ops_status",
        "command_timing_stats",
        "step_prompt_verify",
        "audit_list",
    )
)

MUTATING_COMMAND_NAMES: frozenset[str] = frozenset(
    (
        "plan_create",
        "plan_delete",
        "plan_project_attach",
        "plan_project_detach",
        "plan_project_set_primary",
        "plan_project_clear_primary",
        "plan_import",
        "export_archive",
        "hrs_import",
        "export_cleanup",
        "para_label_assign",
        "para_mark_non_binding",
        "concept_add",
        "concept_update",
        "concept_remove",
        "relation_add",
        "relation_update",
        "relation_remove",
        "step_create",
        "step_update",
        "step_move",
        "step_delete",
        "step_set_status",
        "step_transition",
        "step_dependency_add",
        "step_dependency_remove",
        "step_dependency_set",
        "step_dependency_clear",
        "step_dependency_apply",
        "cascade_begin",
        "cascade_commit",
        "cascade_abort",
        "plan_unfreeze",
        "bug_reanchor",
        "todo_reanchor",
    )
)


def assert_facade_complete(facade_cls: Type[object]) -> None:
    """Assert every name in COMMAND_NAMES has a public async method on facade_cls."""
    missing = sorted(
        name
        for name in COMMAND_NAMES
        if not inspect.iscoroutinefunction(getattr(facade_cls, name, None))
    )
    if missing:
        raise AssertionError(
            f"facade {facade_cls.__name__} is missing methods for: {missing}"
        )


def assert_facade_commands_registered(facade_cls: Type[object]) -> None:
    """Assert every public async method on facade_cls is a canonical command name."""
    orphaned = sorted(
        name
        for name, member in inspect.getmembers(
            facade_cls, predicate=inspect.iscoroutinefunction
        )
        if not name.startswith("_") and name not in COMMAND_NAMES
    )
    if orphaned:
        raise AssertionError(
            f"facade {facade_cls.__name__} exposes non-canonical methods: {orphaned}"
        )


def assert_removed_commands_absent(
    facade_cls: Type[object], removed: Iterable[str]
) -> None:
    """Assert none of the given removed command names still has a facade method."""
    lingering = sorted(
        name
        for name in removed
        if inspect.iscoroutinefunction(getattr(facade_cls, name, None))
    )
    if lingering:
        raise AssertionError(
            f"facade {facade_cls.__name__} retains removed commands: {lingering}"
        )


__all__ = [
    "COMMAND_NAMES",
    "MUTATING_COMMAND_NAMES",
    "assert_facade_complete",
    "assert_facade_commands_registered",
    "assert_removed_commands_absent",
]
