"""Runtime overlay importer: re-creates runtime overlay records from a RuntimeOverlaySnapshot via the sibling create_* store functions, remapping cross-referenced runtime UUIDs as fresh identities are assigned, and never mutating frozen plan truth (C-034)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from plan_manager.runtime.overlay_snapshot import RuntimeOverlaySnapshot
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.domain.bug_source import BugSource
from plan_manager.storage.todo_store import create_todo
from plan_manager.storage.todo_link_store import create_todo_link
from plan_manager.storage.model_binding_store import create_model_binding
from plan_manager.storage.runtime_comment_store import add_comment
from plan_manager.storage.execution_attempt_store import create_execution_attempt
from plan_manager.storage.review_result_store import create_review_result
from plan_manager.storage.escalation_store import create_escalation
from plan_manager.storage.bug_report_store import create_bug
from plan_manager.storage.bug_impact_store import create_bug_impact
from plan_manager.storage.project_dependency_store import create_project_dependency
from plan_manager.storage.bug_fix_store import create_bug_fix
from plan_manager.storage.bug_fix_propagation_store import create_bug_fix_propagation
from plan_manager.storage.cascade_request_store import create_cascade_request


SECTION_IDENTITY_KEYS: dict[str, str] = {
    "todo_items": "todo_uuid",
    "todo_links": "link_uuid",
    "model_bindings": "uuid",
    "runtime_comments": "comment_uuid",
    "execution_attempts": "attempt_uuid",
    "review_results": "review_uuid",
    "escalations": "escalation_uuid",
    "bug_reports": "uuid",
    "bug_impacts": "uuid",
    "project_dependencies": "uuid",
    "bug_fixes": "uuid",
    "bug_fix_propagations": "uuid",
    "runtime_audit_log": "uuid",
    "cascade_requests": "uuid",
}


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value is not None else None


def _remapped(value: str | None, remap: dict[str, str]) -> str | None:
    if value is None:
        return None
    return remap.get(value, value)


def _anchor_from_record(record: dict[str, Any], remap: dict[str, str]) -> PrimaryAnchor:
    ref_id = _remapped(record.get("anchor_ref_id"), remap)
    return PrimaryAnchor(
        anchor_type=record["primary_anchor_type"],
        project_id=_uuid_or_none(record.get("anchor_project_id")),
        file_path=record.get("anchor_file_path"),
        plan_uuid=_uuid_or_none(record.get("anchor_plan_uuid")),
        revision_uuid=_uuid_or_none(record.get("anchor_revision_uuid")),
        step_uuid=_uuid_or_none(record.get("anchor_step_uuid")),
        step_path=record.get("anchor_step_path"),
        ref_id=_uuid_or_none(ref_id),
    )


def _bug_source_from_record(record: dict[str, Any], remap: dict[str, str]) -> BugSource:
    ref_id = _remapped(record.get("source_ref_id"), remap)
    return BugSource(
        source_type=record["source_anchor_type"],
        project_id=_uuid_or_none(record.get("source_project_id")),
        file_path=record.get("source_file_path"),
        plan_uuid=_uuid_or_none(record.get("source_plan_uuid")),
        revision_uuid=_uuid_or_none(record.get("source_revision_uuid")),
        step_uuid=_uuid_or_none(record.get("source_step_uuid")),
        step_path=record.get("source_step_path"),
        ref_id=_uuid_or_none(ref_id),
        command=record.get("source_command"),
        service=record.get("source_service"),
    )


def import_runtime_overlay(
    conn: psycopg.Connection, snapshot: RuntimeOverlaySnapshot, *, changed_by: str
) -> dict[str, int]:
    """Re-create every runtime overlay record described by snapshot.

    Processes sections in a fixed order (todo_items, todo_links,
    model_bindings, escalations, bug_reports, bug_impacts, bug_fixes,
    execution_attempts, review_results, bug_fix_propagations,
    project_dependencies, runtime_comments, cascade_requests) so that a
    runtime entity is always created before any later section that
    cross-references it. A flat old-uuid-string -> new-uuid-string remap is
    built incrementally; every cross-referenced runtime UUID field is looked up
    in this remap before being passed to the corresponding create_* function,
    falling back to the original exported UUID when the referenced entity was
    not yet created in this run (the sibling validators for such forward
    references perform structural UUID validation only, never existence
    enforcement, so a fallback value is safe). Fields referencing frozen plan
    truth or external projects (plan_uuid, step_uuid, revision_uuid, project
    ids) are passed through unchanged; they are never remapped.

    The old identity of each record is read from the payload key named by
    SECTION_IDENTITY_KEYS for that section, NOT from a hardcoded "uuid" key:
    the authoritative sibling to_payload() methods key identity per entity
    (todo_items at "todo_uuid", runtime_comments at "comment_uuid",
    execution_attempts at "attempt_uuid", escalations at "escalation_uuid",
    while model_bindings, bug_reports, bug_impacts, bug_fixes,
    bug_fix_propagations, and cascade_requests emit their primary key under
    "uuid"). Reading the wrong key would silently break every downstream
    cross-reference for those sections.

    This function never mutates frozen plan truth: it only calls sibling
    create_* functions, none of which write to a frozen-truth table. Returns a
    dict of section name -> number of records created; runtime_audit_log is not
    directly reinserted (no sibling function accepts a caller-supplied audit
    uuid/timestamp) and always maps to 0, since each create_* call above already
    appends its own fresh audit trail entry internally. cascade_requests are
    re-created via create_cascade_request, which is create-only: the imported
    request always lands with status "open" (the store exposes no status
    parameter). The original status is preserved in the snapshot payload for
    audit but is not restorable through this import; origin_id (the runtime
    record that raised the request) is remapped like any other runtime
    reference, with the safe fallback described above, while plan_uuid and
    revision_uuid pass through unchanged as frozen plan truth.
    """
    remap: dict[str, str] = {}
    counts: dict[str, int] = {}

    todo_records = snapshot.todo_items.to_payload()["records"]
    for record in todo_records:
        anchor = _anchor_from_record(record, remap)
        created = create_todo(
            conn,
            title=record["title"],
            description=record["description"],
            kind=record["kind"],
            priority_nice=record["priority_nice"],
            created_by=changed_by,
            anchor=anchor,
            status=record["status"],
            assigned_to=record.get("assigned_to"),
            due_at=record.get("due_at"),
            blocking_reason=record.get("blocking_reason"),
            execution_result=record.get("execution_result"),
        )
        remap[record[SECTION_IDENTITY_KEYS["todo_items"]]] = str(created.todo_uuid)
    counts["todo_items"] = len(todo_records)

    todo_link_records = snapshot.todo_links.to_payload()["records"]
    for record in todo_link_records:
        create_todo_link(
            conn,
            from_todo_uuid=uuid.UUID(_remapped(record["from_todo_uuid"], remap)),
            to_todo_uuid=uuid.UUID(_remapped(record["to_todo_uuid"], remap)),
            link_type=record["link_type"],
            created_by=changed_by,
        )
    counts["todo_links"] = len(todo_link_records)

    model_binding_records = snapshot.model_bindings.to_payload()["records"]
    for record in model_binding_records:
        created = create_model_binding(
            conn,
            scope=record["scope"],
            provider=record["provider"],
            model=record["model"],
            max_retries=record["max_retries"],
            timeout=record["timeout"],
            created_by=changed_by,
            role=record.get("role"),
            plan_uuid=_uuid_or_none(record.get("plan_uuid")),
            spec_level=record.get("spec_level"),
            branch_step_uuid=_uuid_or_none(record.get("branch_step_uuid")),
            revision_uuid=_uuid_or_none(record.get("revision_uuid")),
            step_uuid=_uuid_or_none(record.get("step_uuid")),
            step_path=record.get("step_path"),
            fallback_provider=record.get("fallback_provider"),
            fallback_model=record.get("fallback_model"),
            context_budget=record.get("context_budget"),
            active=record["active"],
        )
        remap[record[SECTION_IDENTITY_KEYS["model_bindings"]]] = str(created.binding_uuid)
    counts["model_bindings"] = len(model_binding_records)

    escalation_records = snapshot.escalations.to_payload()["records"]
    for record in escalation_records:
        anchor = _anchor_from_record(record, remap)
        created = create_escalation(
            conn,
            anchor=anchor,
            reason=record["reason"],
            created_by=changed_by,
            from_level=record.get("from_level"),
            to_level=record.get("to_level"),
        )
        remap[record[SECTION_IDENTITY_KEYS["escalations"]]] = str(created.escalation_uuid)
    counts["escalations"] = len(escalation_records)

    bug_report_records = snapshot.bug_reports.to_payload()["records"]
    for record in bug_report_records:
        source = _bug_source_from_record(record, remap)
        created = create_bug(
            conn,
            title=record["title"],
            short_description=record["short_description"],
            detailed_description=record["detailed_description"],
            kind=record["kind"],
            severity=record["severity"],
            priority_nice=record["priority_nice"],
            reporter=record["reporter"],
            created_by=changed_by,
            source=source,
            status=record["status"],
            owner=record.get("owner"),
            expected_behavior=record.get("expected_behavior"),
            actual_behavior=record.get("actual_behavior"),
            reproduction=record.get("reproduction"),
            evidence=record.get("evidence"),
            environment=record.get("environment"),
            duplicate_of_uuid=_uuid_or_none(_remapped(record.get("duplicate_of_uuid"), remap)),
            parent_bug_uuid=_uuid_or_none(_remapped(record.get("parent_bug_uuid"), remap)),
        )
        remap[record[SECTION_IDENTITY_KEYS["bug_reports"]]] = str(created.bug_uuid)
    counts["bug_reports"] = len(bug_report_records)

    bug_impact_records = snapshot.bug_impacts.to_payload()["records"]
    for record in bug_impact_records:
        created = create_bug_impact(
            conn,
            bug_uuid=uuid.UUID(_remapped(record["bug_uuid"], remap)),
            target_type=record["target_type"],
            impact_type=record["impact_type"],
            created_by=changed_by,
            status=record["status"],
            reason=record.get("reason"),
            discovery_method=record.get("discovery_method"),
            target_project_id=_uuid_or_none(record.get("target_project_id")),
            target_file_path=record.get("target_file_path"),
            target_plan_uuid=_uuid_or_none(record.get("target_plan_uuid")),
            target_revision_uuid=_uuid_or_none(record.get("target_revision_uuid")),
            target_step_uuid=_uuid_or_none(record.get("target_step_uuid")),
            target_step_path=record.get("target_step_path"),
            target_ref_id=_uuid_or_none(_remapped(record.get("target_ref_id"), remap)),
            target_identifier=record.get("target_identifier"),
        )
        remap[record[SECTION_IDENTITY_KEYS["bug_impacts"]]] = str(created.impact_uuid)
    counts["bug_impacts"] = len(bug_impact_records)

    bug_fix_records = snapshot.bug_fixes.to_payload()["records"]
    for record in bug_fix_records:
        created = create_bug_fix(
            conn,
            bug_uuid=uuid.UUID(_remapped(record["bug_uuid"], remap)),
            fix_type=record["fix_type"],
            summary=record["summary"],
            author=record["author"],
            created_by=changed_by,
            status=record["status"],
            implementation_notes=record.get("implementation_notes"),
            source_project_id=_uuid_or_none(record.get("source_project_id")),
            branch=record.get("branch"),
            commit_hash=record.get("commit_hash"),
            pull_request=record.get("pull_request"),
            changed_files=record.get("changed_files"),
            tests=record.get("tests"),
            reviewer=record.get("reviewer"),
            verification_method=record.get("verification_method"),
            expected_result=record.get("expected_result"),
        )
        remap[record[SECTION_IDENTITY_KEYS["bug_fixes"]]] = str(created.fix_uuid)
    counts["bug_fixes"] = len(bug_fix_records)

    execution_attempt_records = snapshot.execution_attempts.to_payload()["records"]
    for record in execution_attempt_records:
        created = create_execution_attempt(
            conn,
            plan_uuid=uuid.UUID(record["plan_uuid"]),
            step_uuid=uuid.UUID(record["step_uuid"]),
            status=record["status"],
            created_by=changed_by,
            revision_uuid=_uuid_or_none(record.get("revision_uuid")),
            step_path=record.get("step_path"),
            todo_uuid=_uuid_or_none(_remapped(record.get("todo_uuid"), remap)),
            bug_fix_uuid=_uuid_or_none(_remapped(record.get("bug_fix_uuid"), remap)),
            assigned_binding_uuid=_uuid_or_none(_remapped(record.get("assigned_binding_uuid"), remap)),
            assigned_provider=record.get("assigned_provider"),
            assigned_model=record.get("assigned_model"),
            used_provider=record.get("used_provider"),
            used_model=record.get("used_model"),
            runtime=record.get("runtime"),
            vast_instance_id=record.get("vast_instance_id"),
            input_context_hash=record.get("input_context_hash"),
            parent_attempt_uuid=_uuid_or_none(_remapped(record.get("parent_attempt_uuid"), remap)),
        )
        remap[record[SECTION_IDENTITY_KEYS["execution_attempts"]]] = str(created.attempt_uuid)
    counts["execution_attempts"] = len(execution_attempt_records)

    review_result_records = snapshot.review_results.to_payload()["records"]
    for record in review_result_records:
        create_review_result(
            conn,
            object_type=record["object_type"],
            reviewer=record["reviewer"],
            status=record["status"],
            created_by=changed_by,
            reviewed_attempt_uuid=_uuid_or_none(_remapped(record.get("reviewed_attempt_uuid"), remap)),
            reviewed_revision_uuid=_uuid_or_none(record.get("reviewed_revision_uuid")),
            findings=record.get("findings"),
            evidence=record.get("evidence"),
            verification_commands=record.get("verification_commands"),
            escalation_target_uuid=_uuid_or_none(_remapped(record.get("escalation_target_uuid"), remap)),
        )
    counts["review_results"] = len(review_result_records)

    bug_fix_propagation_records = snapshot.bug_fix_propagations.to_payload()["records"]
    for record in bug_fix_propagation_records:
        create_bug_fix_propagation(
            conn,
            bug_fix_uuid=uuid.UUID(_remapped(record["bug_fix_uuid"], remap)),
            impact_uuid=uuid.UUID(_remapped(record["impact_uuid"], remap)),
            action=record["action"],
            created_by=changed_by,
            status=record["status"],
            target_type=record.get("target_type"),
            target_identifier=record.get("target_identifier"),
            assigned_to=record.get("assigned_to"),
            linked_todo_uuid=_uuid_or_none(_remapped(record.get("linked_todo_uuid"), remap)),
            linked_plan_uuid=_uuid_or_none(record.get("linked_plan_uuid")),
            linked_cascade_uuid=_uuid_or_none(record.get("linked_cascade_uuid")),
        )
    counts["bug_fix_propagations"] = len(bug_fix_propagation_records)

    project_dependency_records = snapshot.project_dependencies.to_payload()["records"]
    for record in project_dependency_records:
        create_project_dependency(
            conn,
            dependent_project_id=uuid.UUID(record["dependent_project_id"]),
            depends_on_project_id=uuid.UUID(record["depends_on_project_id"]),
            dependency_type=record["dependency_type"],
            discovery_source=record["discovery_source"],
            created_by=changed_by,
            confidence=record["confidence"],
            version_constraint=record.get("version_constraint"),
            active=record["active"],
        )
    counts["project_dependencies"] = len(project_dependency_records)

    runtime_comment_records = snapshot.runtime_comments.to_payload()["records"]
    for record in runtime_comment_records:
        anchor = _anchor_from_record(record, remap)
        created = add_comment(
            conn,
            anchor=anchor,
            kind=record["kind"],
            visibility=record["visibility"],
            author=record["author"],
            body=record["body"],
            created_by=changed_by,
            resolved=record.get("resolved"),
            supersedes_comment_uuid=_uuid_or_none(_remapped(record.get("supersedes_comment_uuid"), remap)),
        )
        remap[record[SECTION_IDENTITY_KEYS["runtime_comments"]]] = str(created.comment_uuid)
    counts["runtime_comments"] = len(runtime_comment_records)

    cascade_request_records = snapshot.cascade_requests.to_payload()["records"]
    for record in cascade_request_records:
        create_cascade_request(
            conn,
            plan_uuid=uuid.UUID(record["plan_uuid"]),
            revision_uuid=_uuid_or_none(record.get("revision_uuid")),
            target_artifact=record["target_artifact"],
            target_step_path=record.get("target_step_path"),
            origin_kind=record["origin_kind"],
            origin_id=_uuid_or_none(_remapped(record.get("origin_id"), remap)),
            reason=record["reason"],
            created_by=changed_by,
        )
    counts["cascade_requests"] = len(cascade_request_records)

    counts["runtime_audit_log"] = 0
    return counts
