"""Read-only runtime overlay exporter: assembles a RuntimeOverlaySnapshot for one plan by reading every runtime overlay store's list_* function, the runtime audit trail, and the cascade-request log. Deliberately separate from plan_manager.exchange.exporter (the normative plan export) and must never import it (C-034)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg

from plan_manager.runtime.overlay_snapshot import (
    RuntimeOverlaySnapshot,
    TodoItemsSection,
    TodoLinksSection,
    ModelBindingsSection,
    RuntimeCommentsSection,
    ExecutionAttemptsSection,
    ReviewResultsSection,
    EscalationsSection,
    BugReportsSection,
    BugImpactsSection,
    ProjectDependenciesSection,
    BugFixesSection,
    BugFixPropagationsSection,
    RuntimeAuditLogSection,
    CascadeRequestsSection,
)
from plan_manager.storage.todo_store import list_todos
from plan_manager.storage.todo_link_store import list_todo_links
from plan_manager.storage.model_binding_store import list_model_bindings
from plan_manager.storage.runtime_comment_store import list_comments
from plan_manager.storage.execution_attempt_store import list_execution_attempts
from plan_manager.storage.review_result_store import list_review_results
from plan_manager.storage.escalation_store import list_escalations
from plan_manager.storage.bug_report_store import list_bugs
from plan_manager.storage.bug_impact_store import list_bug_impacts
from plan_manager.storage.project_dependency_store import list_project_dependencies
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.runtime_audit_store import list_runtime_audit
from plan_manager.storage.cascade_request_store import list_cascade_requests


def export_runtime_overlay(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> RuntimeOverlaySnapshot:
    """Assemble a RuntimeOverlaySnapshot of the current runtime overlay state.

    Sections whose store list_* function accepts a plan-scoping parameter
    (model_bindings, runtime_comments, execution_attempts, runtime_audit_log,
    cascade_requests) are filtered to plan_uuid. Sections whose store list_*
    function accepts no plan-scoping parameter (todo_items, todo_links,
    review_results, escalations, bug_reports, bug_impacts, project_dependencies,
    bug_fixes, bug_fix_propagations) are read in full, with no cross-referencing
    filter invented beyond what each store signature directly supports.

    include_deleted handling (each choice verified against the defining store
    AS, not assumed): every one of the twelve overlay stores below defines an
    include_deleted keyword and is therefore called with include_deleted=True so
    the snapshot captures soft-deleted rows too. The runtime audit store is
    append-only and defines NO include_deleted parameter (soft deletion is
    itself an appended action, never a removed row), so list_runtime_audit is
    called plainly. The cascade-request store likewise defines NO include_deleted
    parameter, so list_cascade_requests is called with plan_uuid only.

    This function performs read (SELECT) operations only; it never writes.
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    todo_items = list_todos(conn, include_deleted=True)  # todo_store defines include_deleted
    todo_links = list_todo_links(conn, include_deleted=True)  # todo_link_store defines include_deleted
    model_bindings = list_model_bindings(conn, plan_uuid=plan_uuid, include_deleted=True)  # model_binding_store defines include_deleted
    runtime_comments = list_comments(conn, anchor_plan_uuid=plan_uuid, include_deleted=True)  # runtime_comment_store defines include_deleted
    execution_attempts = list_execution_attempts(conn, plan_uuid=plan_uuid, include_deleted=True)  # execution_attempt_store defines include_deleted
    review_results = list_review_results(conn, include_deleted=True)  # review_result_store defines include_deleted
    escalations = list_escalations(conn, include_deleted=True)  # escalation_store defines include_deleted
    bug_reports = list_bugs(conn, include_deleted=True)  # bug_report_store defines include_deleted
    bug_impacts = list_bug_impacts(conn, include_deleted=True)  # bug_impact_store defines include_deleted
    project_dependencies = list_project_dependencies(conn, include_deleted=True)  # project_dependency_store defines include_deleted
    bug_fixes = list_bug_fixes(conn, include_deleted=True)  # bug_fix_store defines include_deleted
    bug_fix_propagations = list_bug_fix_propagations(conn, include_deleted=True)  # bug_fix_propagation_store defines include_deleted
    runtime_audit_log = list_runtime_audit(conn, plan_uuid=plan_uuid)  # append-only store: no include_deleted parameter
    cascade_requests = list_cascade_requests(conn, plan_uuid=plan_uuid)  # cascade_request_store: no include_deleted parameter

    return RuntimeOverlaySnapshot(
        plan_uuid=plan_uuid,
        generated_at=generated_at,
        todo_items=TodoItemsSection(records=[r.to_payload() for r in todo_items]),
        todo_links=TodoLinksSection(records=[r.to_payload() for r in todo_links]),
        model_bindings=ModelBindingsSection(records=[r.to_payload() for r in model_bindings]),
        runtime_comments=RuntimeCommentsSection(records=[r.to_payload() for r in runtime_comments]),
        execution_attempts=ExecutionAttemptsSection(records=[r.to_payload() for r in execution_attempts]),
        review_results=ReviewResultsSection(records=[r.to_payload() for r in review_results]),
        escalations=EscalationsSection(records=[r.to_payload() for r in escalations]),
        bug_reports=BugReportsSection(records=[r.to_payload() for r in bug_reports]),
        bug_impacts=BugImpactsSection(records=[r.to_payload() for r in bug_impacts]),
        project_dependencies=ProjectDependenciesSection(records=[r.to_payload() for r in project_dependencies]),
        bug_fixes=BugFixesSection(records=[r.to_payload() for r in bug_fixes]),
        bug_fix_propagations=BugFixPropagationsSection(
            records=[r.to_payload() for r in bug_fix_propagations]
        ),
        runtime_audit_log=RuntimeAuditLogSection(records=[r.to_payload() for r in runtime_audit_log]),
        cascade_requests=CascadeRequestsSection(records=[r.to_payload() for r in cascade_requests]),
    )
