"""Pure mappers normalizing each work source record into a unified WorkItem (C-027)."""
from __future__ import annotations

from plan_manager.runtime.work_item import WorkItem, AsReadyItem, WorkKind
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.review_result import ReviewResult
from plan_manager.domain.escalation import Escalation


def work_item_from_as_ready(item: AsReadyItem) -> WorkItem:
    """Map AsReadyItem to AS_READY WorkItem."""
    return WorkItem(
        work_kind=WorkKind.AS_READY.value,
        source_uuid=item.step_uuid,
        title=item.step_path,
        priority_nice=item.priority_nice,
        ready=item.ready,
        requires_runtime=True,
        execution_wave=item.execution_wave,
        created_at=item.created_at,
        plan_uuid=item.plan_uuid,
        step_uuid=item.step_uuid,
        step_path=item.step_path,
        assigned_provider=item.assigned_provider,
        assigned_model=item.assigned_model,
        lock_keys=item.lock_keys,
    )


def work_item_from_todo(todo: TodoItem) -> WorkItem:
    """Map TodoItem to TODO WorkItem."""
    return WorkItem(
        work_kind=WorkKind.TODO.value,
        source_uuid=todo.todo_uuid,
        title=todo.title,
        priority_nice=todo.priority_nice,
        ready=(todo.status == "ready"),
        requires_runtime=False,
        due_at=todo.due_at,
        created_at=todo.created_at,
        plan_uuid=todo.anchor_plan_uuid,
        step_uuid=todo.anchor_step_uuid,
        step_path=todo.anchor_step_path,
    )


def work_item_from_bug_report(bug: BugReport) -> WorkItem:
    """Map BugReport to BUG_INVESTIGATION WorkItem."""
    return WorkItem(
        work_kind=WorkKind.BUG_INVESTIGATION.value,
        source_uuid=bug.bug_uuid,
        title=bug.title,
        priority_nice=bug.priority_nice,
        ready=True,
        requires_runtime=False,
        is_blocker=(bug.severity == "blocker"),
        bug_severity=bug.severity,
        created_at=bug.created_at,
        plan_uuid=bug.source_plan_uuid,
        step_uuid=bug.source_step_uuid,
        step_path=bug.source_step_path,
    )


def work_item_from_bug_fix(fix: BugFix) -> WorkItem:
    """Map BugFix to BUG_FIX WorkItem."""
    return WorkItem(
        work_kind=WorkKind.BUG_FIX.value,
        source_uuid=fix.fix_uuid,
        title=fix.summary,
        priority_nice=0,
        ready=True,
        requires_runtime=False,
        created_at=fix.created_at,
    )


def work_item_from_propagation(prop: BugFixPropagation) -> WorkItem:
    """Map BugFixPropagation to PROPAGATION WorkItem."""
    return WorkItem(
        work_kind=WorkKind.PROPAGATION.value,
        source_uuid=prop.propagation_uuid,
        title=prop.action,
        priority_nice=0,
        ready=(prop.status == "ready"),
        requires_runtime=False,
        created_at=prop.created_at,
        plan_uuid=prop.linked_plan_uuid,
    )


def work_item_from_execution_attempt(attempt: ExecutionAttempt) -> WorkItem:
    """Map ExecutionAttempt to VERIFICATION WorkItem."""
    return WorkItem(
        work_kind=WorkKind.VERIFICATION.value,
        source_uuid=attempt.attempt_uuid,
        title=(attempt.result_summary or "execution attempt"),
        priority_nice=0,
        ready=(attempt.status == "needs_review"),
        requires_runtime=False,
        created_at=attempt.created_at,
        plan_uuid=attempt.plan_uuid,
        step_uuid=attempt.step_uuid,
        step_path=attempt.step_path,
        assigned_provider=attempt.used_provider,
        assigned_model=attempt.used_model,
    )


def work_item_from_review_result(review: ReviewResult) -> WorkItem:
    """Map ReviewResult to REVIEW WorkItem."""
    return WorkItem(
        work_kind=WorkKind.REVIEW.value,
        source_uuid=review.review_uuid,
        title=("review: " + review.status),
        priority_nice=0,
        ready=(review.status in {"changes_requested", "needs_owner_decision", "escalated"}),
        requires_runtime=False,
        created_at=review.created_at,
    )


def work_item_from_escalation(esc: Escalation) -> WorkItem:
    """Map Escalation to ESCALATION WorkItem."""
    return WorkItem(
        work_kind=WorkKind.ESCALATION.value,
        source_uuid=esc.escalation_uuid,
        title=esc.reason,
        priority_nice=0,
        ready=(esc.status == "open"),
        requires_runtime=False,
        created_at=esc.created_at,
        plan_uuid=esc.anchor_plan_uuid,
        step_uuid=esc.anchor_step_uuid,
        step_path=esc.anchor_step_path,
    )
