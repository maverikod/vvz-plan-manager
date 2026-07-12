"""Regression tests for 0.1.28 friction {3fgu}b: every runtime entity's to_payload() must expose
a uniform "uuid" key equal to str(<primary key>), alongside its existing entity-specific key,
mirroring the precedent set by plan_manager.domain.bug_report.BugReport.to_payload() (which
already returns both "uuid" and "bug_uuid").

Pure domain-object tests: each record is constructed directly (no DB), covering exactly the
to_payload() methods edited for this fix (todo.py, runtime_comment.py, todo_link.py,
execution_attempt.py, review_result.py, escalation.py). bug_fix.py, bug_impact.py,
bug_fix_propagation.py, project_dependency.py, and model_binding.py already carried a "uuid" key
before this fix and are covered too, to guard against future regressions removing it.
"""
from __future__ import annotations

import uuid

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.project_dependency import ProjectDependency
from plan_manager.domain.review_result import ReviewResult
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.todo_link import TodoLink

NOW = "2026-07-12T00:00:00+00:00"


def test_todo_item_to_payload_has_uniform_uuid_key() -> None:
    todo_uuid = uuid.uuid4()
    record = TodoItem(
        todo_uuid=todo_uuid,
        title="t",
        description="d",
        kind="task",
        status="open",
        priority_nice=0,
        created_by="x",
        assigned_to=None,
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        resolved_at=None,
        due_at=None,
        primary_anchor_type="none",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        blocking_reason=None,
        execution_result=None,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(todo_uuid)
    assert payload["todo_uuid"] == str(todo_uuid)


def test_runtime_comment_to_payload_has_uniform_uuid_key() -> None:
    comment_uuid = uuid.uuid4()
    record = RuntimeComment(
        comment_uuid=comment_uuid,
        primary_anchor_type="plan",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=uuid.uuid4(),
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        kind="comment",
        visibility="audit_only",
        author="a",
        body="b",
        resolved=None,
        supersedes_comment_uuid=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(comment_uuid)
    assert payload["comment_uuid"] == str(comment_uuid)


def test_todo_link_to_payload_has_uniform_uuid_key() -> None:
    link_uuid = uuid.uuid4()
    record = TodoLink(
        link_uuid=link_uuid,
        from_todo_uuid=uuid.uuid4(),
        to_todo_uuid=uuid.uuid4(),
        link_type="blocks",
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(link_uuid)
    assert payload["link_uuid"] == str(link_uuid)


def test_execution_attempt_to_payload_has_uniform_uuid_key() -> None:
    attempt_uuid = uuid.uuid4()
    record = ExecutionAttempt(
        attempt_uuid=attempt_uuid,
        plan_uuid=uuid.uuid4(),
        revision_uuid=None,
        step_uuid=uuid.uuid4(),
        step_path=None,
        todo_uuid=None,
        bug_fix_uuid=None,
        assigned_binding_uuid=None,
        assigned_provider=None,
        assigned_model=None,
        used_provider=None,
        used_model=None,
        runtime=None,
        vast_instance_id=None,
        started_at=None,
        finished_at=None,
        status="queued",
        input_context_hash=None,
        result_summary=None,
        changed_files=None,
        command_test_results=None,
        resource_accounting=None,
        error=None,
        escalation_reason=None,
        parent_attempt_uuid=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(attempt_uuid)
    assert payload["attempt_uuid"] == str(attempt_uuid)


def test_review_result_to_payload_has_uniform_uuid_key() -> None:
    review_uuid = uuid.uuid4()
    record = ReviewResult(
        review_uuid=review_uuid,
        object_type="execution_attempt",
        reviewed_attempt_uuid=uuid.uuid4(),
        reviewed_revision_uuid=None,
        reviewer="r",
        status="accepted",
        findings=None,
        evidence=None,
        verification_commands=None,
        escalation_target_uuid=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(review_uuid)
    assert payload["review_uuid"] == str(review_uuid)


def test_escalation_to_payload_has_uniform_uuid_key() -> None:
    escalation_uuid = uuid.uuid4()
    record = Escalation(
        escalation_uuid=escalation_uuid,
        primary_anchor_type="none",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        reason="r",
        from_level="ts",
        to_level="gs",
        status="open",
        resolution=None,
        resolved_by=None,
        resolved_at=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(escalation_uuid)
    assert payload["escalation_uuid"] == str(escalation_uuid)


# --- regression guard: modules that already carried "uuid" before this fix ----------------


def test_bug_fix_to_payload_already_has_uniform_uuid_key() -> None:
    fix_uuid = uuid.uuid4()
    record = BugFix(
        fix_uuid=fix_uuid,
        bug_uuid=uuid.uuid4(),
        status="proposed",
        fix_type="code",
        summary="s",
        implementation_notes=None,
        source_project_id=None,
        branch=None,
        commit_hash=None,
        pull_request=None,
        changed_files=None,
        tests=None,
        author="a",
        reviewer=None,
        started_at=None,
        implemented_at=None,
        verified_at=None,
        verification_method=None,
        expected_result=None,
        actual_result=None,
        passed=None,
        revert_info=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(fix_uuid)
    assert payload["bug_uuid"] == str(record.bug_uuid)


def test_bug_impact_to_payload_already_has_uniform_uuid_key() -> None:
    impact_uuid = uuid.uuid4()
    record = BugImpact(
        impact_uuid=impact_uuid,
        bug_uuid=uuid.uuid4(),
        target_type="project",
        target_project_id=None,
        target_file_path=None,
        target_plan_uuid=None,
        target_revision_uuid=None,
        target_step_uuid=None,
        target_step_path=None,
        target_ref_id=None,
        target_identifier=None,
        impact_type="unknown",
        status="suspected",
        reason=None,
        skip_decided_by=None,
        discovery_method=None,
        resolution_evidence=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        resolved_at=None,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(impact_uuid)


def test_bug_fix_propagation_to_payload_already_has_uniform_uuid_key() -> None:
    propagation_uuid = uuid.uuid4()
    record = BugFixPropagation(
        propagation_uuid=propagation_uuid,
        bug_fix_uuid=uuid.uuid4(),
        impact_uuid=uuid.uuid4(),
        target_type=None,
        target_identifier=None,
        action="rebuild_package",
        status="pending",
        assigned_to=None,
        linked_todo_uuid=None,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at=None,
        finished_at=None,
        evidence=None,
        verification_result=None,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(propagation_uuid)


def test_project_dependency_to_payload_already_has_uniform_uuid_key() -> None:
    dependency_uuid = uuid.uuid4()
    record = ProjectDependency(
        dependency_uuid=dependency_uuid,
        dependent_project_id=uuid.uuid4(),
        depends_on_project_id=uuid.uuid4(),
        dependency_type="library",
        version_constraint=None,
        discovery_source="manual",
        confidence="confirmed",
        active=True,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(dependency_uuid)


def test_model_binding_to_payload_already_has_uniform_uuid_key() -> None:
    binding_uuid = uuid.uuid4()
    record = ModelBinding(
        binding_uuid=binding_uuid,
        scope="system",
        role=None,
        plan_uuid=None,
        spec_level=None,
        branch_step_uuid=None,
        revision_uuid=None,
        step_uuid=None,
        step_path=None,
        provider="p",
        model="m",
        fallback_provider=None,
        fallback_model=None,
        max_retries=1,
        timeout=60,
        context_budget=None,
        active=True,
        created_by="x",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )
    payload = record.to_payload()
    assert payload["uuid"] == str(binding_uuid)
