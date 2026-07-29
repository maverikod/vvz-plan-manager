"""CR-6 compatibility and audit contract regression suite (C-016).

Guards two append-only vocabularies and the audit coverage of every mutating
command CR-6 adds. Mocked internals only; no live database.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.storage.runtime_audit_store import ALLOWED_ACTIONS

# ---------------------------------------------------------------------------
# Frozen pre-CR-6 baselines. Copied verbatim from the shipped vocabularies at
# authoring time. Both are append-only: a value is never removed or renamed,
# because recorded audit rows and client error handling keep referring to them.
# ---------------------------------------------------------------------------

DOMAIN_CODES_BASELINE = frozenset({
    "AMBIGUOUS_PARENT_STEP_ID", "AMBIGUOUS_STEP_ID", "AS_SAME_FILE_ORDER_AMBIGUOUS",
    "BUG_FIX_NOT_FOUND", "BUG_IMPACT_NOT_FOUND", "BUG_NOT_FOUND", "BUG_PROPAGATION_NOT_FOUND",
    "CALENDAR_ENTRY_NOT_FOUND", "CASCADE_CONFLICT", "CASCADE_REQUIRED", "COMMENT_NOT_FOUND",
    "COMMON_BLOCK_NOT_FOUND", "CONCEPT_NOT_FOUND", "CONCEPT_OUT_OF_SCOPE",
    "CONTEXT_BLOCKS_MISSING", "CYCLE_DETECTED", "DELETE_BLOCKED", "DEPENDENCY_CYCLE",
    "DEPENDENCY_STEP_NOT_FOUND", "DUPLICATE_ID", "DUPLICATE_LINK", "DUPLICATE_PROJECT_BINDING",
    "DUPLICATE_PROJECT_DEPENDENCY", "EMBEDDINGS_UNAVAILABLE", "ESCALATION_NOT_FOUND",
    "EXECUTION_ATTEMPT_NOT_FOUND", "EXPORT_FILE_NOT_FOUND", "EXPORT_PATH_INVALID",
    "FROZEN_ARTIFACT", "FROZEN_TRUTH_WRITE", "GATE_RED", "GRAPH_CORRUPTED_CHAIN",
    "IMPORT_INVALID", "INVALID_ANCHOR", "INVALID_BINDING_SCOPE", "INVALID_CANDIDATE_CONTENT",
    "INVALID_CONTEXT_BLOCK_KIND", "INVALID_DEPENDENCY_SCOPE", "INVALID_EXECUTION_MODE",
    "INVALID_FILTER", "INVALID_LEVEL", "INVALID_NICE_PRIORITY", "INVALID_PAGINATION",
    "INVALID_PROFILE_SCOPE", "INVALID_PROJECT_ID", "INVALID_ROLE", "INVALID_RUNTIME_ROLE",
    "INVALID_RUNTIME_STATUS_TRANSITION", "INVALID_SCOPE", "INVALID_STATUS_FILTER",
    "INVALID_STEP_FIELD_SHAPE", "INVALID_TRANSITION", "INVALID_VISIBILITY",
    "INVOCATION_PROFILE_NOT_FOUND", "LINK_CYCLE", "MODEL_BINDING_NOT_FOUND", "MODEL_NOT_FOUND",
    "NODE_NOT_FOUND", "NO_APPLICABLE_ASSIGNMENT", "PARAGRAPH_NOT_FOUND", "PARENT_STEP_INVALID",
    "PLAN_COMPLETED", "PLAN_NOT_FOUND", "PLAN_NOT_FULLY_FROZEN", "PRIMARY_PROJECT_NOT_BOUND",
    "PROFILE_RESOLUTION_FAILED", "PROJECT_DEPENDENCY_CYCLE", "PROJECT_DEPENDENCY_NOT_FOUND",
    "PROJECT_NOT_ATTACHED_TO_PLAN", "PROJECT_NOT_BOUND_TO_PLAN", "PROMPT_ASSEMBLY_FAILED",
    "PROVIDER_NOT_FOUND", "RELATION_NOT_FOUND", "REVIEW_RESULT_NOT_FOUND",
    "REVISION_NOT_FOUND", "ROLE_MODEL_RESOLUTION_FAILED", "ROLE_NOT_FOUND",
    "RUNTIME_LINK_NOT_FOUND", "RUNTIME_VALIDATION_ERROR", "SELF_CERTIFICATION_FORBIDDEN",
    "SELF_DEPENDENCY", "SNAPSHOT_NOT_FOUND", "STEP_NOT_FOUND", "TODO_LINK_NOT_FOUND",
    "TODO_NOT_FOUND", "TOOLSET_MEMBERSHIP_NOT_FOUND", "TOOLSET_NOT_FOUND", "TOOL_NOT_FOUND",
    "UNKNOWN_STEP_SELECTOR", "VERDICT_STALE", "WISH_NOT_FOUND",
})

MUTATING_BASELINE = frozenset({
    "block_rebuild", "bug_delete", "bug_fix_delete", "bug_fix_propagation_delete",
    "bug_impact_delete", "bug_reanchor", "calendar_entry_create", "calendar_entry_delete",
    "calendar_entry_update", "cascade_abort", "cascade_begin", "cascade_commit", "concept_add",
    "concept_remove", "concept_update", "export_archive", "export_cleanup", "hrs_import",
    "invocation_profile_create", "invocation_profile_delete", "invocation_profile_update",
    "model_create", "model_delete", "model_update", "para_delete", "para_insert",
    "para_label_assign", "para_mark_non_binding", "para_update", "plan_comment_set",
    "plan_completed_set", "plan_create", "plan_delete", "plan_import", "plan_project_attach",
    "plan_project_clear_primary", "plan_project_detach", "plan_project_set_primary",
    "plan_unfreeze", "provider_create", "provider_delete", "provider_set_status",
    "provider_update", "relation_add", "relation_remove", "relation_update", "role_create",
    "role_delete", "role_update", "step_create", "step_delete", "step_dependency_add",
    "step_dependency_apply", "step_dependency_clear", "step_dependency_remove",
    "step_dependency_set", "step_move", "step_set_status", "step_transition", "step_update",
    "todo_reanchor", "tool_create", "tool_delete", "tool_update", "toolset_create",
    "toolset_delete", "toolset_member_add", "toolset_member_remove", "toolset_update",
    "wish_create", "wish_delete", "wish_update",
})

ALLOWED_ACTIONS_BASELINE = frozenset({
    "create", "update", "soft_delete", "hard_delete", "archive", "restore",
    "plan_unfreeze", "subtree_unfreeze", "cascade_begin", "cascade_commit",
    "cascade_abort", "plan_completed_set", "plan_comment_set",
})

# Commands CR-6 introduces. runtime_purge_batch arrives with G-004; until then
# the audit-coverage test simply finds fewer commands to exercise, which is
# why it derives its work list from the inventory rather than from this literal.
_CR6_COMMANDS = frozenset({"project_uuid_reserve", "runtime_purge_batch"})


def test_domain_codes_baseline_preserved() -> None:
    """No domain code is ever removed or renamed."""
    missing = DOMAIN_CODES_BASELINE - DOMAIN_CODES
    assert missing == frozenset(), f"domain codes removed since the baseline: {sorted(missing)}"


def test_allowed_actions_baseline_preserved() -> None:
    """No audit action is ever removed or renamed."""
    missing = ALLOWED_ACTIONS_BASELINE - ALLOWED_ACTIONS
    assert missing == frozenset(), f"audit actions removed since the baseline: {sorted(missing)}"


def test_mutating_baseline_preserved() -> None:
    """A command never silently stops being classified as mutating."""
    missing = MUTATING_BASELINE - MUTATING
    assert missing == frozenset(), f"commands no longer classified mutating: {sorted(missing)}"


def _advertised_codes() -> set[str]:
    """Every code advertised in any registered command's metadata error_cases."""
    advertised: set[str] = set()
    for name in INVENTORY:
        module_name = f"plan_manager.commands.{name}_command"
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if getattr(obj, "name", None) != name:
                continue
            try:
                cases = obj.metadata().get("error_cases") or {}
            except Exception:
                continue
            advertised |= set(cases)
    return advertised


def test_new_domain_codes_advertised_by_commands() -> None:
    """Every code CR-6 adds is advertised by at least one command.

    A registered-but-unadvertised code is unreachable: no caller can learn it
    exists. The pre-existing reachability contract enforces this for the whole
    vocabulary; this test states it specifically for CR-6's additions so a
    failure names the plan that introduced the gap.
    """
    added = DOMAIN_CODES - DOMAIN_CODES_BASELINE
    if not added:
        pytest.skip("CR-6 has not added a domain code yet")
    advertised = _advertised_codes()
    unreachable = sorted(code for code in added if code not in advertised)
    assert unreachable == [], f"CR-6 codes advertised by no command: {unreachable}"


def test_new_audit_actions_are_documented_in_the_matrix() -> None:
    """Every action CR-6 adds appears in the normative coverage matrix."""
    import pathlib

    added = ALLOWED_ACTIONS - ALLOWED_ACTIONS_BASELINE
    if not added:
        pytest.skip("CR-6 has not added an audit action yet")
    matrix = pathlib.Path(__file__).resolve().parent.parent / "docs" / "delivery" / "cr6-audit-coverage-matrix.md"
    assert matrix.exists(), f"the normative audit coverage matrix is missing at {matrix}"
    text = matrix.read_text()
    undocumented = sorted(action for action in added if action not in text)
    assert undocumented == [], f"audit actions absent from the coverage matrix: {undocumented}"


@contextmanager
def _fake_db():
    yield object()


def test_cr6_mutating_commands_write_a_registered_audit_action(monkeypatch) -> None:
    """Every mutating command CR-6 adds audits with a registered action.

    Exercised through the command's own execute path with the database and the
    audit store replaced by fakes, so the assertion is on the action value the
    command actually passes, not on what its metadata claims.
    """
    exercised: list[str] = []
    for name in sorted(_CR6_COMMANDS & set(MUTATING)):
        module = importlib.import_module(f"plan_manager.commands.{name}_command")
        recorded: list[dict] = []
        monkeypatch.setattr(module, "db_connection", _fake_db, raising=False)
        monkeypatch.setattr(
            module,
            "record_runtime_change",
            lambda conn, **kwargs: recorded.append(kwargs),
            raising=False,
        )

        if name == "project_uuid_reserve":
            monkeypatch.setattr(
                module,
                "reserve_project_uuid",
                lambda conn, entity_id, reserved_by, note: {
                    "id": entity_id,
                    "project_uuid": entity_id,
                    "kind": "project_reservation",
                    "reserved_by": reserved_by,
                    "note": note,
                    "created_at": "2026-07-30T00:00:00+00:00",
                },
                raising=False,
            )
            command_cls = next(
                obj
                for _, obj in inspect.getmembers(module, inspect.isclass)
                if getattr(obj, "name", None) == name
            )
            asyncio.run(
                command_cls().execute(
                    action="reserve",
                    project_uuid=str(uuid.uuid4()),
                    reserved_by="contract-test",
                )
            )
        else:
            # A CR-6 mutating command with no exercise recipe here is a gap in
            # this test, not a pass: fail loudly rather than skip silently.
            pytest.fail(
                f"{name} is a CR-6 mutating command with no exercise recipe in this suite"
            )

        assert recorded, f"{name} wrote no audit record"
        for call in recorded:
            action = call.get("action")
            assert action in ALLOWED_ACTIONS, (
                f"{name} audited with action {action!r}, which is not in ALLOWED_ACTIONS"
            )
            assert "plan_uuid" in call, (
                f"{name} omitted plan_uuid, a required keyword of record_runtime_change"
            )
        exercised.append(name)

    assert exercised, "no CR-6 mutating command was exercised"
