"""Pure round-trip test for RuntimeOverlaySnapshot plus an import-separation guard for overlay_export (C-034)."""

from __future__ import annotations

import ast
import inspect
import uuid

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


def _empty_snapshot(plan_uuid: uuid.UUID | None) -> RuntimeOverlaySnapshot:
    return RuntimeOverlaySnapshot(
        plan_uuid=plan_uuid,
        generated_at="2026-07-10T00:00:00+00:00",
        todo_items=TodoItemsSection(records=[]),
        todo_links=TodoLinksSection(records=[]),
        model_bindings=ModelBindingsSection(records=[]),
        runtime_comments=RuntimeCommentsSection(records=[]),
        execution_attempts=ExecutionAttemptsSection(records=[]),
        review_results=ReviewResultsSection(records=[]),
        escalations=EscalationsSection(records=[]),
        bug_reports=BugReportsSection(records=[]),
        bug_impacts=BugImpactsSection(records=[]),
        project_dependencies=ProjectDependenciesSection(records=[]),
        bug_fixes=BugFixesSection(records=[]),
        bug_fix_propagations=BugFixPropagationsSection(records=[]),
        runtime_audit_log=RuntimeAuditLogSection(records=[]),
        cascade_requests=CascadeRequestsSection(records=[]),
    )


def test_runtime_overlay_snapshot_round_trip_with_records() -> None:
    plan_uuid = uuid.uuid4()
    todo_uuid = str(uuid.uuid4())
    request_uuid = str(uuid.uuid4())
    snapshot = _empty_snapshot(plan_uuid)
    snapshot = RuntimeOverlaySnapshot(
        plan_uuid=snapshot.plan_uuid,
        generated_at=snapshot.generated_at,
        todo_items=TodoItemsSection(
            records=[
                {
                    "todo_uuid": todo_uuid,
                    "title": "sample todo",
                    "description": "sample description",
                    "kind": "task",
                    "status": "open",
                    "priority_nice": 0,
                    "created_by": "tester",
                }
            ]
        ),
        todo_links=snapshot.todo_links,
        model_bindings=snapshot.model_bindings,
        runtime_comments=snapshot.runtime_comments,
        execution_attempts=snapshot.execution_attempts,
        review_results=snapshot.review_results,
        escalations=snapshot.escalations,
        bug_reports=snapshot.bug_reports,
        bug_impacts=snapshot.bug_impacts,
        project_dependencies=snapshot.project_dependencies,
        bug_fixes=snapshot.bug_fixes,
        bug_fix_propagations=snapshot.bug_fix_propagations,
        runtime_audit_log=snapshot.runtime_audit_log,
        cascade_requests=CascadeRequestsSection(
            records=[
                {
                    "uuid": request_uuid,
                    "plan_uuid": str(plan_uuid),
                    "revision_uuid": None,
                    "target_artifact": "MRS",
                    "target_step_path": None,
                    "origin_kind": "todo",
                    "origin_id": todo_uuid,
                    "reason": "sample cascade reason",
                    "status": "promoted",
                    "created_by": "tester",
                    "created_at": "2026-07-10T00:00:00+00:00",
                    "updated_at": "2026-07-10T00:00:00+00:00",
                }
            ]
        ),
    )

    payload = snapshot.to_payload()
    restored = RuntimeOverlaySnapshot.from_payload(payload)

    assert restored.to_payload() == payload
    assert restored.plan_uuid == plan_uuid
    assert restored.todo_items.records[0]["title"] == "sample todo"
    assert restored.todo_items.records[0]["todo_uuid"] == todo_uuid
    assert restored.cascade_requests.records[0]["uuid"] == request_uuid
    assert restored.cascade_requests.records[0]["status"] == "promoted"


def test_runtime_overlay_snapshot_empty_round_trip() -> None:
    snapshot = _empty_snapshot(None)
    payload = snapshot.to_payload()
    restored = RuntimeOverlaySnapshot.from_payload(payload)

    assert restored.to_payload() == payload
    assert payload["plan_uuid"] is None
    assert payload["todo_items"] == {"records": []}
    assert payload["runtime_audit_log"] == {"records": []}
    assert payload["cascade_requests"] == {"records": []}


def test_overlay_export_does_not_import_normative_exporter() -> None:
    import plan_manager.runtime.overlay_export as overlay_export_module

    source = inspect.getsource(overlay_export_module)
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    assert "plan_manager.exchange.exporter" not in imported_modules
    assert "plan_manager.exchange.importer" not in imported_modules
