"""Pure mappers from runtime records to prompt-context sections, incl. comment-visibility gating (C-028)."""
from __future__ import annotations

from plan_manager.runtime.prompt_context import (
    PromptContextTodo,
    PromptContextBug,
    PromptContextNote,
    PromptContextAttempt,
    PromptContextReview,
    PromptContextModelBinding,
    PromptContextEscalation,
)
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.review_result import ReviewResult
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.model_resolution import ModelResolution
from plan_manager.domain.comment_visibility import may_reach_context


def to_context_todo(todo: TodoItem) -> PromptContextTodo:
    return PromptContextTodo(todo.todo_uuid, todo.title, todo.kind, todo.status, todo.priority_nice)


def to_context_bug(bug: BugReport) -> PromptContextBug:
    return PromptContextBug(bug.bug_uuid, bug.title, bug.severity, bug.status)


def filter_visible_notes(comments: list[RuntimeComment], context_kind: str) -> list[PromptContextNote]:
    result = []
    for comment in comments:
        if may_reach_context(comment.visibility, context_kind):
            result.append(PromptContextNote(comment.comment_uuid, comment.kind, comment.visibility, comment.body))
    return result


def to_context_attempt(attempt: ExecutionAttempt) -> PromptContextAttempt:
    return PromptContextAttempt(attempt.attempt_uuid, attempt.status, attempt.result_summary, attempt.error)


def to_context_review(review: ReviewResult) -> PromptContextReview:
    return PromptContextReview(review.review_uuid, review.status, review.findings)


def to_context_binding(resolution: ModelResolution) -> PromptContextModelBinding:
    return PromptContextModelBinding(resolution.source_binding_uuid, resolution.effective_provider,
                                     resolution.effective_model, resolution.source)


def to_context_escalation(esc: Escalation) -> PromptContextEscalation:
    return PromptContextEscalation(esc.escalation_uuid, esc.reason, esc.status)
