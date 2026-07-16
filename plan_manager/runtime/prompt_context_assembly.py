"""Assemble the runtime prompt-context section for a target step, anchor- and visibility-filtered, size-limited (C-028)."""
from __future__ import annotations

import uuid

import psycopg

from plan_manager.runtime.prompt_context import (
    RuntimePromptContext,
    PromptContextLimits,
    DEFAULT_PROMPT_CONTEXT_LIMITS,
)
from plan_manager.runtime.prompt_context_sources import (
    to_context_todo,
    to_context_bug,
    filter_visible_notes,
    to_context_attempt,
    to_context_review,
    to_context_binding,
    to_context_escalation,
)
from plan_manager.storage.todo_store import list_todos
from plan_manager.storage.bug_report_store import list_bugs
from plan_manager.storage.runtime_comment_store import list_comments
from plan_manager.storage.execution_attempt_store import list_execution_attempts
from plan_manager.storage.review_result_store import list_review_results
from plan_manager.storage.escalation_store import list_escalations
from plan_manager.storage.model_binding_store import list_bindings_for_resolution
from plan_manager.domain.model_resolution import (
    ResolutionTarget,
    ModelResolutionError,
    resolve_effective_binding,
)


def assemble_runtime_prompt_context(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID,
    step_uuid: uuid.UUID,
    step_path: str | None,
    context_kind: str,
    resolution_target: ResolutionTarget,
    limits: PromptContextLimits = DEFAULT_PROMPT_CONTEXT_LIMITS,
) -> RuntimePromptContext:
    truncated = False

    # Step 1: TODOs
    all_todos = list_todos(conn)
    kept_todos = [
        todo
        for todo in all_todos
        if (todo.anchor_step_uuid == step_uuid or todo.anchor_plan_uuid == plan_uuid)
        and todo.status in {"open", "in_progress", "blocked"}
    ]
    mapped_todos = [to_context_todo(todo) for todo in kept_todos]
    if len(mapped_todos) > limits.max_todos:
        todos = mapped_todos[: limits.max_todos]
        truncated = True
    else:
        todos = mapped_todos

    # Step 2: Blocker bugs
    all_bugs = list_bugs(conn, severity="blocker")
    kept_bugs = [
        bug
        for bug in all_bugs
        if bug.status in {
            "reported",
            "triaged",
            "confirmed",
            "fixing",
            "propagating",
            "reopened",
        }
    ]
    mapped_bugs = [to_context_bug(bug) for bug in kept_bugs]
    if len(mapped_bugs) > limits.max_bugs:
        blocker_bugs = mapped_bugs[: limits.max_bugs]
        truncated = True
    else:
        blocker_bugs = mapped_bugs

    # Step 3: Notes
    all_comments = list_comments(conn, anchor_step_uuid=step_uuid)
    filtered_notes = filter_visible_notes(all_comments, context_kind)
    if len(filtered_notes) > limits.max_notes:
        notes = filtered_notes[: limits.max_notes]
        truncated = True
    else:
        notes = filtered_notes

    # Step 4: Failed attempts
    all_failed_attempts = list_execution_attempts(
        conn, plan_uuid=plan_uuid, step_uuid=step_uuid, status="failed"
    )
    mapped_failed_attempts = [to_context_attempt(attempt) for attempt in all_failed_attempts]
    if len(mapped_failed_attempts) > limits.max_attempts:
        failed_attempts = mapped_failed_attempts[: limits.max_attempts]
        truncated = True
    else:
        failed_attempts = mapped_failed_attempts

    # Step 5: Review findings
    all_attempts = list_execution_attempts(
        conn, plan_uuid=plan_uuid, step_uuid=step_uuid
    )
    all_reviews = []
    for attempt in all_attempts:
        reviews = list_review_results(conn, reviewed_attempt_uuid=attempt.attempt_uuid)
        all_reviews.extend(reviews)
    mapped_reviews = [to_context_review(review) for review in all_reviews]
    if len(mapped_reviews) > limits.max_reviews:
        review_findings = mapped_reviews[: limits.max_reviews]
        truncated = True
    else:
        review_findings = mapped_reviews

    # Step 6: Model binding
    candidates = list_bindings_for_resolution(conn, plan_uuid=plan_uuid)
    try:
        resolution = resolve_effective_binding(candidates, resolution_target)
        model_binding = to_context_binding(resolution)
    except ModelResolutionError:
        model_binding = None

    # Step 7: Escalations
    all_escalations = list_escalations(conn, status="open")
    kept_escalations = [
        esc for esc in all_escalations if esc.anchor_step_uuid == step_uuid
    ]
    mapped_escalations = [to_context_escalation(esc) for esc in kept_escalations]
    if len(mapped_escalations) > limits.max_escalations:
        escalations = mapped_escalations[: limits.max_escalations]
        truncated = True
    else:
        escalations = mapped_escalations

    # Step 8: Build and return RuntimePromptContext
    return RuntimePromptContext(
        target_plan_uuid=plan_uuid,
        target_step_uuid=step_uuid,
        target_step_path=step_path,
        context_kind=context_kind,
        todos=todos,
        blocker_bugs=blocker_bugs,
        notes=notes,
        failed_attempts=failed_attempts,
        review_findings=review_findings,
        model_binding=model_binding,
        escalations=escalations,
        truncated=truncated,
    )
