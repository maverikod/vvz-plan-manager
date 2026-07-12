"""Build the single unified runtime work queue across plans and runtime entities (C-027)."""
from __future__ import annotations

import psycopg
from plan_manager.runtime.work_item import WorkItem, AsReadyItem, ResourceAvailability
from plan_manager.runtime.work_ordering import order_queue, pause_dependent_as
from plan_manager.runtime.work_sources import (
    work_item_from_as_ready, work_item_from_todo, work_item_from_bug_report, work_item_from_bug_fix,
    work_item_from_propagation, work_item_from_execution_attempt, work_item_from_review_result,
    work_item_from_escalation,
)
from plan_manager.storage.todo_store import list_todos
from plan_manager.storage.bug_report_store import list_bugs
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.execution_attempt_store import list_execution_attempts
from plan_manager.storage.review_result_store import list_review_results
from plan_manager.storage.escalation_store import list_escalations

TODO_ACTIVE_STATUSES = frozenset({"open", "ready", "in_progress", "blocked"})
BUG_OPEN_STATUSES = frozenset({"reported", "triaged", "confirmed", "fixing", "propagating", "reopened"})
FIX_UNFINISHED_STATUSES = frozenset({"proposed", "in_progress", "implemented", "partial"})
PROPAGATION_OPEN_STATUSES = frozenset({"pending", "ready", "in_progress", "blocked", "failed"})
ATTEMPT_VERIFICATION_STATUSES = frozenset({"needs_review"})
REVIEW_OPEN_STATUSES = frozenset({"changes_requested", "needs_owner_decision", "escalated"})


def build_unified_queue(
    conn: psycopg.Connection, *, as_ready: list[AsReadyItem], availability: ResourceAvailability,
) -> list[WorkItem]:
    """Build the unified work queue from all work sources. Read-only; never mutates plan truth."""
    # Step 1: Start with AS ready for execution
    items: list[WorkItem] = [work_item_from_as_ready(a) for a in as_ready]

    # Step 2: Add active TODOs
    for todo in list_todos(conn):
        if todo.status in TODO_ACTIVE_STATUSES:
            items.append(work_item_from_todo(todo))

    # Step 3: Add open bugs
    for bug in list_bugs(conn):
        if bug.status in BUG_OPEN_STATUSES:
            items.append(work_item_from_bug_report(bug))

    # Step 4: Add unfinished bug fixes
    for fix in list_bug_fixes(conn):
        if fix.status in FIX_UNFINISHED_STATUSES:
            items.append(work_item_from_bug_fix(fix))

    # Step 5: Add open bug fix propagations
    for prop in list_bug_fix_propagations(conn):
        if prop.status in PROPAGATION_OPEN_STATUSES:
            items.append(work_item_from_propagation(prop))

    # Step 6: Add execution attempts pending verification
    for att in list_execution_attempts(conn):
        if att.status in ATTEMPT_VERIFICATION_STATUSES:
            items.append(work_item_from_execution_attempt(att))

    # Step 7: Add open review results
    for rev in list_review_results(conn):
        if rev.status in REVIEW_OPEN_STATUSES:
            items.append(work_item_from_review_result(rev))

    # Step 8: Add escalations (reader filters to open)
    for esc in list_escalations(conn, status="open"):
        items.append(work_item_from_escalation(esc))

    # Step 9: Flag AS items paused by blockers or high-priority TODOs
    items = pause_dependent_as(items)

    # Step 10: Return queue in deterministic C-027 order
    return order_queue(items, availability)
