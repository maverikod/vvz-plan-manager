"""Project dependency persistence: CRUD + reverse-graph discovery over project_dependency with audit + soft delete (C-023)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.project_dependency import (
    ProjectDependency, DEPENDENCY_TYPES, DISCOVERY_SOURCES, DEPENDENCY_CONFIDENCES,
    validate_dependency_type, validate_discovery_source, validate_confidence,
    validate_dependency_project_ids, guard_discovery_not_silently_confirmed,
    guard_no_dependency_cycle, suspected_impact_targets,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change

_COLUMNS = (
    "uuid", "dependent_project_id", "depends_on_project_id", "dependency_type",
    "version_constraint", "discovery_source", "confidence", "active",
    "created_by", "created_at", "updated_at", "deleted_at",
)


def _row_to_record(row: tuple[Any, ...]) -> ProjectDependency:
    return ProjectDependency(
        dependency_uuid=row[0],
        dependent_project_id=row[1],
        depends_on_project_id=row[2],
        dependency_type=row[3],
        version_constraint=row[4],
        discovery_source=row[5],
        confidence=row[6],
        active=row[7],
        created_by=row[8],
        created_at=row[9].isoformat(),
        updated_at=row[10].isoformat(),
        deleted_at=row[11].isoformat() if row[11] is not None else None,
    )


def _load_active_edges(conn: psycopg.Connection) -> list[tuple[str, str]]:
    cur = conn.execute(
        "SELECT dependent_project_id, depends_on_project_id FROM project_dependency "
        "WHERE deleted_at IS NULL AND active",
    )
    return [(str(r[0]), str(r[1])) for r in cur.fetchall()]


def create_project_dependency(
    conn: psycopg.Connection,
    *,
    dependent_project_id: uuid.UUID,
    depends_on_project_id: uuid.UUID,
    dependency_type: str,
    discovery_source: str,
    created_by: str,
    confidence: str = "unconfirmed",
    version_constraint: str | None = None,
    active: bool = True,
) -> ProjectDependency:
    validate_dependency_type(dependency_type)
    validate_discovery_source(discovery_source)
    validate_confidence(confidence)
    validate_dependency_project_ids(dependent_project_id, depends_on_project_id)
    guard_discovery_not_silently_confirmed(discovery_source, confidence)

    edges = _load_active_edges(conn)
    edges.append((str(dependent_project_id), str(depends_on_project_id)))
    guard_no_dependency_cycle(edges)

    dependency_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO project_dependency ("
        "uuid, dependent_project_id, depends_on_project_id, dependency_type, "
        "version_constraint, discovery_source, confidence, active, "
        "created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            dependency_uuid, dependent_project_id, depends_on_project_id, dependency_type,
            version_constraint, discovery_source, confidence, active,
            created_by, now, now, None,
        ),
    )
    record_runtime_change(
        conn, plan_uuid=None, entity_type="project_dependency", entity_id=dependency_uuid,
        action="create", changed_by=created_by,
    )
    return ProjectDependency(
        dependency_uuid=dependency_uuid,
        dependent_project_id=dependent_project_id,
        depends_on_project_id=depends_on_project_id,
        dependency_type=dependency_type,
        version_constraint=version_constraint,
        discovery_source=discovery_source,
        confidence=confidence,
        active=active,
        created_by=created_by,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        deleted_at=None,
    )


def get_project_dependency(conn: psycopg.Connection, dependency_uuid: uuid.UUID) -> ProjectDependency | None:
    cur = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM project_dependency WHERE uuid = %s",
        (dependency_uuid,),
    )
    row = cur.fetchone()
    return _row_to_record(row) if row is not None else None


def list_project_dependencies(
    conn: psycopg.Connection,
    *,
    dependent_project_id: uuid.UUID | None = None,
    depends_on_project_id: uuid.UUID | None = None,
    active_only: bool = False,
    include_deleted: bool = False,
) -> list[ProjectDependency]:
    clauses: list[str] = []
    params: list[Any] = []
    if dependent_project_id is not None:
        clauses.append("dependent_project_id = %s")
        params.append(dependent_project_id)
    if depends_on_project_id is not None:
        clauses.append("depends_on_project_id = %s")
        params.append(depends_on_project_id)
    if active_only:
        clauses.append("active")
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    cur = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM project_dependency{where} ORDER BY created_at ASC",
        params,
    )
    return [_row_to_record(r) for r in cur.fetchall()]


def list_reverse_dependents(conn: psycopg.Connection, project_id: uuid.UUID) -> list[ProjectDependency]:
    cur = conn.execute(
        f"SELECT {', '.join(_COLUMNS)} FROM project_dependency "
        "WHERE depends_on_project_id = %s AND deleted_at IS NULL AND active "
        "ORDER BY created_at ASC",
        (project_id,),
    )
    return [_row_to_record(r) for r in cur.fetchall()]


def discover_suspected_targets(conn: psycopg.Connection, source_project_id: uuid.UUID) -> list[uuid.UUID]:
    edges = _load_active_edges(conn)
    return suspected_impact_targets(edges, source_project_id)


def confirm_project_dependency(conn: psycopg.Connection, dependency_uuid: uuid.UUID, *, changed_by: str) -> ProjectDependency:
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE project_dependency SET confidence = %s, updated_at = %s WHERE uuid = %s",
        ("confirmed", now, dependency_uuid),
    )
    record_runtime_change(
        conn, plan_uuid=None, entity_type="project_dependency", entity_id=dependency_uuid,
        action="update", changed_by=changed_by,
    )
    record = get_project_dependency(conn, dependency_uuid)
    if record is None:
        raise RuntimeValidationError(f"project_dependency {dependency_uuid} not found after confirm")
    return record


def remove_project_dependency(conn: psycopg.Connection, dependency_uuid: uuid.UUID, *, changed_by: str) -> ProjectDependency:
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE project_dependency SET deleted_at = %s, updated_at = %s WHERE uuid = %s",
        (now, now, dependency_uuid),
    )
    record_runtime_change(
        conn, plan_uuid=None, entity_type="project_dependency", entity_id=dependency_uuid,
        action="soft_delete", changed_by=changed_by,
    )
    record = get_project_dependency(conn, dependency_uuid)
    if record is None:
        raise RuntimeValidationError(f"project_dependency {dependency_uuid} not found after soft delete")
    return record
