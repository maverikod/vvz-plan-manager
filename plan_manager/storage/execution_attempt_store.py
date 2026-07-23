"""Execution attempt persistence: create/report per-run records over execution_attempt with audit + soft delete (C-016)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.execution_attempt import (
    ExecutionAttempt, ATTEMPT_STATUSES, TERMINAL_ATTEMPT_STATUSES,
    validate_attempt_status, is_terminal_status,
    validate_resource_accounting, validate_transcript_ref,
)
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


_COLUMNS = (
    "uuid", "plan_uuid", "revision_uuid", "step_uuid", "step_path", "todo_uuid",
    "bug_fix_uuid", "assigned_binding_uuid", "assigned_provider", "assigned_model",
    "used_provider", "used_model", "runtime", "vast_instance_id", "started_at",
    "finished_at", "status", "input_context_hash", "result_summary", "changed_files",
    "command_test_results", "resource_accounting", "error", "escalation_reason",
    "parent_attempt_uuid", "created_by", "created_at", "updated_at", "deleted_at",
    "acct_tokens_in", "acct_tokens_out", "acct_provider", "acct_model", "acct_wall_ms",
    "acct_cost_estimate", "transcript_ref",
)


def _row_to_record(row: tuple[Any, ...]) -> ExecutionAttempt:
    """Map a raw execution_attempt row (in _COLUMNS order) to an ExecutionAttempt record."""
    data = dict(zip(_COLUMNS, row))
    return ExecutionAttempt(
        attempt_uuid=data["uuid"],
        plan_uuid=data["plan_uuid"],
        revision_uuid=data["revision_uuid"],
        step_uuid=data["step_uuid"],
        step_path=data["step_path"],
        todo_uuid=data["todo_uuid"],
        bug_fix_uuid=data["bug_fix_uuid"],
        assigned_binding_uuid=data["assigned_binding_uuid"],
        assigned_provider=data["assigned_provider"],
        assigned_model=data["assigned_model"],
        used_provider=data["used_provider"],
        used_model=data["used_model"],
        runtime=data["runtime"],
        vast_instance_id=data["vast_instance_id"],
        started_at=data["started_at"].isoformat() if data["started_at"] is not None else None,
        finished_at=data["finished_at"].isoformat() if data["finished_at"] is not None else None,
        status=data["status"],
        input_context_hash=data["input_context_hash"],
        result_summary=data["result_summary"],
        changed_files=data["changed_files"],
        command_test_results=data["command_test_results"],
        resource_accounting=data["resource_accounting"],
        acct_tokens_in=data["acct_tokens_in"],
        acct_tokens_out=data["acct_tokens_out"],
        acct_provider=data["acct_provider"],
        acct_model=data["acct_model"],
        acct_wall_ms=data["acct_wall_ms"],
        acct_cost_estimate=float(data["acct_cost_estimate"]) if data["acct_cost_estimate"] is not None else None,
        transcript_ref=data["transcript_ref"],
        error=data["error"],
        escalation_reason=data["escalation_reason"],
        parent_attempt_uuid=data["parent_attempt_uuid"],
        created_by=data["created_by"],
        created_at=data["created_at"].isoformat(),
        updated_at=data["updated_at"].isoformat(),
        deleted_at=data["deleted_at"].isoformat() if data["deleted_at"] is not None else None,
    )


def create_execution_attempt(
    conn: psycopg.Connection, *, plan_uuid: uuid.UUID, step_uuid: uuid.UUID, status: str, created_by: str,
    revision_uuid: uuid.UUID | None = None, step_path: str | None = None,
    todo_uuid: uuid.UUID | None = None, bug_fix_uuid: uuid.UUID | None = None,
    assigned_binding_uuid: uuid.UUID | None = None, assigned_provider: str | None = None,
    assigned_model: str | None = None, used_provider: str | None = None, used_model: str | None = None,
    runtime: str | None = None, vast_instance_id: str | None = None,
    input_context_hash: str | None = None, parent_attempt_uuid: uuid.UUID | None = None,
) -> ExecutionAttempt:
    """Validate status, step anchor, optional assigned binding, and optional parent attempt;
    insert a new execution_attempt row; record an audit create; return the new record."""
    validate_attempt_status(status)
    anchor = PrimaryAnchor(
        anchor_type="step", plan_uuid=plan_uuid, revision_uuid=revision_uuid,
        step_uuid=step_uuid, step_path=step_path,
    )
    validate_anchor(conn, anchor)
    if assigned_binding_uuid is not None:
        check_row_exists(conn, "model_binding", assigned_binding_uuid, frozenset({"model_binding"}))
    if parent_attempt_uuid is not None:
        check_row_exists(conn, "execution_attempt", parent_attempt_uuid, frozenset({"execution_attempt"}))

    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    started_at = now if status == "running" else None

    conn.execute(
        f"INSERT INTO execution_attempt ({', '.join(_COLUMNS)}) "
        f"VALUES ({', '.join(['%s'] * len(_COLUMNS))})",
        (
            new_uuid, plan_uuid, revision_uuid, step_uuid, step_path, todo_uuid,
            bug_fix_uuid, assigned_binding_uuid, assigned_provider, assigned_model,
            used_provider, used_model, runtime, vast_instance_id, started_at,
            None, status, input_context_hash, None, None,
            None, None, None, None,
            parent_attempt_uuid, created_by, now, now, None,
            None, None, None, None, None,
            None, None,
        ),
    )
    record_runtime_change(
        conn, plan_uuid=plan_uuid, entity_type="execution_attempt", entity_id=new_uuid,
        action="create", changed_by=created_by,
    )
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM execution_attempt WHERE uuid = %s", (new_uuid,)
    ).fetchone()
    return _row_to_record(row)


def report_execution_attempt(
    conn: psycopg.Connection, attempt_uuid: uuid.UUID, *, changed_by: str, status: str | None = None,
    used_provider: str | None = None, used_model: str | None = None, result_summary: str | None = None,
    changed_files: list[Any] | None = None, command_test_results: dict[str, Any] | None = None,
    resource_accounting: dict[str, Any] | None = None, error: str | None = None,
    escalation_reason: str | None = None, input_context_hash: str | None = None,
    transcript_ref: str | None = None,
) -> ExecutionAttempt:
    """Patch only the supplied (non-None) fields on an execution_attempt row; stamp
    finished_at when the new status is terminal; validate and project resource_accounting
    onto the typed acct_* columns (C-013) while keeping the resource_accounting jsonb bag as
    the canonical store; validate and persist transcript_ref when supplied; record an audit
    update. Never sets any verified/accepted flag — correctness is recorded separately by a
    ReviewResult (C-016 {7kaw})."""
    now = datetime.now(timezone.utc)
    set_clauses: list[str] = ["updated_at = %s"]
    params: list[Any] = [now]

    if status is not None:
        validate_attempt_status(status)
        set_clauses.append("status = %s")
        params.append(status)
        if is_terminal_status(status):
            set_clauses.append("finished_at = %s")
            params.append(now)
    if used_provider is not None:
        set_clauses.append("used_provider = %s")
        params.append(used_provider)
    if used_model is not None:
        set_clauses.append("used_model = %s")
        params.append(used_model)
    if result_summary is not None:
        set_clauses.append("result_summary = %s")
        params.append(result_summary)
    if changed_files is not None:
        set_clauses.append("changed_files = %s")
        params.append(Jsonb(changed_files))
    if command_test_results is not None:
        set_clauses.append("command_test_results = %s")
        params.append(Jsonb(command_test_results))
    if resource_accounting is not None:
        validated_accounting = validate_resource_accounting(resource_accounting)
        set_clauses.append("resource_accounting = %s")
        params.append(Jsonb(validated_accounting))
        set_clauses.append("acct_tokens_in = %s")
        params.append(validated_accounting["tokens_in"])
        set_clauses.append("acct_tokens_out = %s")
        params.append(validated_accounting["tokens_out"])
        set_clauses.append("acct_provider = %s")
        params.append(validated_accounting["provider"])
        set_clauses.append("acct_model = %s")
        params.append(validated_accounting["model"])
        set_clauses.append("acct_wall_ms = %s")
        params.append(validated_accounting["wall_ms"])
        set_clauses.append("acct_cost_estimate = %s")
        params.append(validated_accounting["cost_estimate"])
    if error is not None:
        set_clauses.append("error = %s")
        params.append(error)
    if escalation_reason is not None:
        set_clauses.append("escalation_reason = %s")
        params.append(escalation_reason)
    if input_context_hash is not None:
        set_clauses.append("input_context_hash = %s")
        params.append(input_context_hash)
    if transcript_ref is not None:
        validated_transcript_ref = validate_transcript_ref(transcript_ref)
        set_clauses.append("transcript_ref = %s")
        params.append(validated_transcript_ref)

    params.append(attempt_uuid)
    conn.execute(
        f"UPDATE execution_attempt SET {', '.join(set_clauses)} WHERE uuid = %s", params
    )
    record_runtime_change(
        conn, plan_uuid=None, entity_type="execution_attempt", entity_id=attempt_uuid,
        action="update", changed_by=changed_by,
    )
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM execution_attempt WHERE uuid = %s", (attempt_uuid,)
    ).fetchone()
    if row is None:
        raise RuntimeValidationError(f"execution attempt not found: {attempt_uuid}")
    return _row_to_record(row)


def get_execution_attempt(conn: psycopg.Connection, attempt_uuid: uuid.UUID) -> ExecutionAttempt | None:
    """Return the ExecutionAttempt with the given uuid, or None if no such row exists."""
    row = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM execution_attempt WHERE uuid = %s", (attempt_uuid,)
    ).fetchone()
    return _row_to_record(row) if row is not None else None


def list_execution_attempts(
    conn: psycopg.Connection, *, plan_uuid: uuid.UUID | None = None, step_uuid: uuid.UUID | None = None,
    status: str | None = None, parent_attempt_uuid: uuid.UUID | None = None, include_deleted: bool = False,
    acct_provider: str | None = None, acct_model: str | None = None,
) -> list[ExecutionAttempt]:
    """List execution_attempt rows filtered by the provided plan_uuid/step_uuid/status/
    parent_attempt_uuid/acct_provider/acct_model; exclude soft-deleted rows unless
    include_deleted is True; order by created_at ascending."""
    clauses: list[str] = []
    params: list[Any] = []
    if plan_uuid is not None:
        clauses.append("plan_uuid = %s")
        params.append(plan_uuid)
    if step_uuid is not None:
        clauses.append("step_uuid = %s")
        params.append(step_uuid)
    if status is not None:
        clauses.append("status = %s")
        params.append(status)
    if parent_attempt_uuid is not None:
        clauses.append("parent_attempt_uuid = %s")
        params.append(parent_attempt_uuid)
    if acct_provider is not None:
        clauses.append("acct_provider = %s")
        params.append(acct_provider)
    if acct_model is not None:
        clauses.append("acct_model = %s")
        params.append(acct_model)
    if not include_deleted:
        clauses.append("deleted_at IS NULL")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM execution_attempt {where_sql} ORDER BY created_at ASC", params
    ).fetchall()
    return [_row_to_record(row) for row in rows]
