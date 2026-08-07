"""Registry of selectable live-smoke regression tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from typing import Sequence


@dataclass(frozen=True)
class LiveSmokeTestSpec:
    """One selectable Tier-4 live-smoke regression test."""

    key: str
    function_name: str
    description: str
    needs_catalog: bool = False
    needs_project: bool = False


LIVE_SMOKE_TEST_SPECS: tuple[LiveSmokeTestSpec, ...] = (
    LiveSmokeTestSpec("r1", "run_r1_todo_anchor_none", "todo anchor none regression"),
    LiveSmokeTestSpec("r2", "run_r2_same_file_order_ambiguity", "same-file order ambiguity regression"),
    LiveSmokeTestSpec("r3", "run_r3_project_view", "project_view parity regression", needs_catalog=True, needs_project=True),
    LiveSmokeTestSpec("r4", "run_r4_ts_inputs_outputs_schema", "TS inputs/outputs schema regression"),
    LiveSmokeTestSpec("r5", "run_r5_step_id_selector_docs", "step-id selector docs regression"),
    LiveSmokeTestSpec("r6", "run_r6_write_intent_negation", "write-intent negation regression"),
    LiveSmokeTestSpec("r7", "run_r7_agent_config_lifecycle", "agent-config lifecycle regression", needs_catalog=True),
    LiveSmokeTestSpec("r8", "run_r8_gs_coverage_live_cascade_read", "GS coverage live cascade read regression"),
    LiveSmokeTestSpec("r9", "run_r9_plan_completion_lock", "plan completion lock regression", needs_catalog=True),
    LiveSmokeTestSpec("r10", "run_r10_branch_scope_hierarchical_selectors", "branch scope hierarchical selector regression"),
    LiveSmokeTestSpec("r11", "run_r11_list_view_projection", "list view projection regression"),
    LiveSmokeTestSpec("r12", "run_r12_response_size_and_cascade_tip_batch", "response-size and cascade-tip batch regression"),
    LiveSmokeTestSpec("r13", "run_r13_bug_list_project_view_bounded", "bug_list/project_view bounded projection regression", needs_project=True),
    LiveSmokeTestSpec("r14", "run_r14_plan_score_as_selector_depth", "plan_score selector-depth regression"),
    LiveSmokeTestSpec("r15", "run_r15_response_size_pagination_batch", "response-size pagination batch regression"),
    LiveSmokeTestSpec("r16", "run_r16_bug_update_append_history", "bug_update append-history regression"),
    LiveSmokeTestSpec("r17", "run_r17_bug_optional_plan_project_anchor", "bug optional plan/project anchor regression", needs_project=True),
    LiveSmokeTestSpec("r18", "run_r18_context_bundle_child_block_identity", "context_bundle child block identity regression"),
    LiveSmokeTestSpec("r19", "run_r19_bug_delete_full_crud_lifecycle", "bug_delete full CRUD lifecycle regression"),
    LiveSmokeTestSpec("r20", "run_r20_bug_impact_optional_plan_a5ec9c1a", "bug_impact optional-plan regression", needs_project=True),
    LiveSmokeTestSpec("r21", "run_r21_typed_invalid_params_concept_add", "typed invalid params concept_add regression"),
    LiveSmokeTestSpec("r22", "run_r22_typed_invalid_params_comment_get", "typed invalid params comment_get regression"),
    LiveSmokeTestSpec("r23", "run_r23_typed_invalid_params_review_result_get", "typed invalid params review_result_get regression"),
    LiveSmokeTestSpec("r24", "run_r24_command_catalog_dump_pagination", "command_catalog_dump pagination regression"),
    LiveSmokeTestSpec("r25", "run_r25_list_summary_default_drops_free_text", "list summary default drops free-text regression"),
    LiveSmokeTestSpec("r26", "run_r26_todo_queue_anchor_plan_scoping", "todo_queue anchor-plan scoping regression"),
    LiveSmokeTestSpec(
        "r27",
        "run_r27_runtime_work_layer_lifecycle",
        "runtime work-layer wish/calendar lifecycle regression",
        needs_catalog=True,
        needs_project=True,
    ),
    LiveSmokeTestSpec(
        "r28",
        "run_r28_bug_delete_dangling_plan_anchor",
        "bug_delete dangling plan-anchor audit regression (bug 1e13649f)",
    ),
    LiveSmokeTestSpec(
        "r29",
        "run_r29_step_transition_branch_scope_freeze_gate",
        "step_transition branch-scope freeze gate regression (bug 36414056)",
    ),
    LiveSmokeTestSpec(
        "r30",
        "run_r30_parallel_map_subtree_closure",
        "graph_parallel_map strict subtree closure regression (todo 19391f0b)",
    ),
    LiveSmokeTestSpec(
        "r31",
        "run_r31_block_rebuild_open_cascade",
        "block_rebuild open-cascade working-state regression (bug e3060750)",
    ),
    LiveSmokeTestSpec(
        "r32",
        "run_r32_unfreeze_audit_names_cascade",
        "plan_unfreeze audit cascade-provenance regression (bug 74ba4313)",
    ),
    LiveSmokeTestSpec(
        "r33",
        "run_r33_project_uuid_reserve_lifecycle",
        "project_uuid_reserve lifecycle: reserve, collision, resolve, release, cleanup",
        needs_catalog=True,
    ),
    LiveSmokeTestSpec(
        "r34",
        "run_r34_reference_inspect_traversal",
        "reference_inspect: direct referrers and recursive traversal with cycle safety",
        needs_catalog=True,
    ),
    LiveSmokeTestSpec(
        "r35",
        "run_r35_work_queue_timestamp_types",
        "todo_queue orders a live bug_fix beside other work sources (bug 4375c341)",
    ),
    LiveSmokeTestSpec(
        "r36",
        "run_r36_soft_delete_owned_column",
        "soft delete hides a row without removing it, for todo and comment (bug 31ba96d5)",
    ),
    LiveSmokeTestSpec(
        "r37",
        "run_r37_cr7_direct_state_acceptance",
        "CR-7 C-012 direct-state acceptance: engine-served CRUD per family, "
        "null-removes-key, cross-kind duplicate rejection",
        needs_catalog=True,
    ),
    LiveSmokeTestSpec(
        "r38",
        "run_r38_export_import_round_trip",
        "CR-7 G-005/T-002/A-002 export/import black-box round trip: plan_export/"
        "export_read/hrs_export, plan_import into a freed name, re-export, and "
        "API-visible comparison (step tree, HRS/MRS, dependencies, statuses, "
        "project bindings, checksum)",
        needs_catalog=True,
        needs_project=True,
    ),
    LiveSmokeTestSpec(
        "r39",
        "run_r39_cr7_invariants",
        "CR-7 G-008/T-001/A-003 live invariant regression: identifier classification "
        "of a newly registered kind, out-of-mechanism absence via registry/relation-"
        "index effects, metadata projection equality, and ownership declared",
        needs_catalog=True,
    ),
    LiveSmokeTestSpec(
        "r40",
        "run_r40_owner_edge_read_projection",
        "bug_list/bug_get/escalation_list explicit read projection after the "
        "0029 owner-edge column (bug 0798c162)",
    ),
)

LIVE_SMOKE_TEST_KEYS: tuple[str, ...] = tuple(spec.key for spec in LIVE_SMOKE_TEST_SPECS)
_LIVE_SMOKE_TEST_BY_KEY = {spec.key: spec for spec in LIVE_SMOKE_TEST_SPECS}


def get_live_smoke_test_spec(key: str) -> LiveSmokeTestSpec:
    """Return one test spec by CLI key."""

    normalized = key.strip().lower()
    return _LIVE_SMOKE_TEST_BY_KEY[normalized]


def resolve_selected_test_specs(selected: Optional[Sequence[str]]) -> list[LiveSmokeTestSpec]:
    """Resolve a CLI selection to ordered specs.

    Empty or omitted selection means "all registered tests", in registry order.
    """

    if not selected:
        return list(LIVE_SMOKE_TEST_SPECS)
    requested = {item.strip().lower() for item in selected if item and item.strip()}
    unknown = sorted(requested - set(LIVE_SMOKE_TEST_KEYS))
    if unknown:
        raise KeyError(f"unknown live-smoke tests: {unknown}")
    return [spec for spec in LIVE_SMOKE_TEST_SPECS if spec.key in requested]


def format_live_smoke_test_listing() -> str:
    """Render a human-readable list of selectable tests."""

    lines = ["Available live-smoke tests:"]
    for spec in LIVE_SMOKE_TEST_SPECS:
        lines.append(f"  {spec.key:>3s}  {spec.description}")
    return "\n".join(lines)


__all__ = [
    "LIVE_SMOKE_TEST_KEYS",
    "LIVE_SMOKE_TEST_SPECS",
    "LiveSmokeTestSpec",
    "format_live_smoke_test_listing",
    "get_live_smoke_test_spec",
    "resolve_selected_test_specs",
]
