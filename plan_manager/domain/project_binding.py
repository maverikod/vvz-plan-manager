"""Optional analysis-server project bindings for plans and steps."""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.plan import Plan
from plan_manager.commands.step_ref import canonical_step_path
from plan_manager.views.dependency_graph import load_steps


def normalize_project_id(value: str) -> str:
    """Return canonical UUID text or raise INVALID_PROJECT_ID."""
    if not isinstance(value, str):
        raise DomainCommandError(
            "INVALID_PROJECT_ID",
            "project_id must be a UUID string",
            {"project_id": value},
        )
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise DomainCommandError(
            "INVALID_PROJECT_ID",
            "project_id must be a valid UUID",
            {"project_id": value},
        )


def validate_plan_projects(project_ids: list[str], primary_project_id: str | None) -> None:
    normalized = [normalize_project_id(project_id) for project_id in project_ids]
    if len(normalized) != len(set(normalized)):
        raise DomainCommandError(
            "DUPLICATE_PROJECT_BINDING",
            "plan project_ids must not contain duplicates",
            {},
        )
    if primary_project_id is not None:
        primary = normalize_project_id(primary_project_id)
        if primary not in normalized:
            raise DomainCommandError(
                "PRIMARY_PROJECT_NOT_BOUND",
                "primary_project_id must be present in project_ids",
                {"primary_project_id": primary},
            )


def require_project_bound(plan: Plan, project_id: str) -> str:
    normalized = normalize_project_id(project_id)
    if normalized not in plan.project_ids:
        raise DomainCommandError(
            "PROJECT_NOT_BOUND_TO_PLAN",
            "project_id is not bound to plan",
            {"project_id": normalized, "plan_uuid": str(plan.uuid)},
        )
    return normalized


def attach_project(
    conn: psycopg.Connection,
    plan: Plan,
    project_id: str,
    *,
    primary: bool = False,
) -> tuple[Plan, bool]:
    normalized = normalize_project_id(project_id)
    project_ids = list(plan.project_ids)
    already_exists = normalized in project_ids
    if not already_exists:
        project_ids.append(normalized)
    primary_project_id = normalized if primary else plan.primary_project_id
    validate_plan_projects(project_ids, primary_project_id)
    conn.execute(
        "UPDATE plan SET project_ids = %s, primary_project_id = %s WHERE uuid = %s",
        (project_ids, primary_project_id, plan.uuid),
    )
    return (
        Plan(
            uuid=plan.uuid,
            name=plan.name,
            status=plan.status,
            context_budget=plan.context_budget,
            head_revision_uuid=plan.head_revision_uuid,
            project_ids=project_ids,
            primary_project_id=primary_project_id,
            deleted_at=plan.deleted_at,
        ),
        already_exists,
    )


def set_primary_project(
    conn: psycopg.Connection,
    plan: Plan,
    project_id: str,
) -> Plan:
    normalized = require_project_bound(plan, project_id)
    conn.execute(
        "UPDATE plan SET primary_project_id = %s WHERE uuid = %s",
        (normalized, plan.uuid),
    )
    return Plan(
        uuid=plan.uuid,
        name=plan.name,
        status=plan.status,
        context_budget=plan.context_budget,
        head_revision_uuid=plan.head_revision_uuid,
        project_ids=list(plan.project_ids),
        primary_project_id=normalized,
        deleted_at=plan.deleted_at,
    )


def clear_primary_project(conn: psycopg.Connection, plan: Plan) -> Plan:
    conn.execute("UPDATE plan SET primary_project_id = NULL WHERE uuid = %s", (plan.uuid,))
    return Plan(
        uuid=plan.uuid,
        name=plan.name,
        status=plan.status,
        context_budget=plan.context_budget,
        head_revision_uuid=plan.head_revision_uuid,
        project_ids=list(plan.project_ids),
        primary_project_id=None,
        deleted_at=plan.deleted_at,
    )


def detach_project(conn: psycopg.Connection, plan: Plan, project_id: str) -> dict:
    normalized = normalize_project_id(project_id)
    if normalized not in plan.project_ids:
        raise DomainCommandError(
            "PROJECT_NOT_ATTACHED_TO_PLAN",
            "project_id is not attached to plan",
            {"project_id": normalized, "plan_uuid": str(plan.uuid)},
        )
    project_ids = [item for item in plan.project_ids if item != normalized]
    cleared_primary = plan.primary_project_id == normalized
    primary_project_id = None if cleared_primary else plan.primary_project_id
    nodes = load_steps(conn, plan.uuid)
    affected = [
        canonical_step_path(nodes, step)
        for step in nodes.values()
        if step.project_id == normalized
    ]
    conn.execute(
        "UPDATE plan SET project_ids = %s, primary_project_id = %s WHERE uuid = %s",
        (project_ids, primary_project_id, plan.uuid),
    )
    conn.execute(
        "UPDATE step SET project_id = NULL WHERE plan_uuid = %s AND project_id = %s",
        (plan.uuid, normalized),
    )
    affected.sort()
    return {
        "plan_uuid": str(plan.uuid),
        "detached_project_id": normalized,
        "project_ids": project_ids,
        "primary_project_id": primary_project_id,
        "cleared_primary": cleared_primary,
        "affected_steps": affected,
    }
