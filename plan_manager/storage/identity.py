"""UUID/name identity mechanism for plan_manager storage.

Full-scope contract. Every persistent entity of Plan Manager takes its
identifier from this registry, not only the plan-truth tables: ALLOWED_TABLES
enumerates every in-scope table and EXCLUDED_TABLES records, with a written
reason, each table deliberately left out. A table in neither set is an
unclassified gap, not an exemption.

The registry answers three questions. Which table owns an identifier
(resolve_entity_identity, resolve_entity_identities_batch). Whether an
identifier is still free for ANY kind (ensure_identity_available, the single
cross-kind collision guard every create path calls). And whether an identifier
has been claimed ahead of creation (reserve_project_uuid /
release_project_reservation, recorded under RESERVED_KIND), so that a future
external project UUID cannot collide with an entity, a plan, or another
reservation.

Registration is transactional: register_entity_identity must run inside the
same transaction as the entity INSERT it describes and never commits.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.storage.errors import DuplicateNameError, NotFoundError


def new_entity_uuid() -> uuid.UUID:
    """Generate a new immutable primary identity for a stored entity.

    Returns:
        uuid.UUID
            A random UUID (uuid.uuid4()). This is the primary identity
            assigned once at creation time to every row in every table
            listed in ALLOWED_TABLES; it never changes for the lifetime
            of the row.
    """
    return uuid.uuid4()


ALLOWED_TABLES = frozenset(
    {
        # Plan-truth tables (the historical scope of this constant).
        "plan",
        "paragraph",
        "concept",
        "relation",
        "step",
        "node_version",
        "revision",
        "ref",
        "cascade",
        "cascade_request",
        "context_block",
        "srt_snapshot",
        "runtime_audit_log",
        # Runtime work-layer entities.
        "todo_item",
        "todo_link",
        "runtime_comment",
        "execution_attempt",
        "review_result",
        "escalation",
        "escalation_policy",
        "answer_envelope",
        "runtime_link",
        "wish_item",
        "calendar_entry",
        # Bug lifecycle entities.
        "bug_report",
        "bug_impact",
        "bug_fix",
        "bug_fix_propagation",
        "project_dependency",
        # Agent-configuration entities.
        "provider",
        "model",
        "model_binding",
        "role",
        "role_model_binding",
        "tool",
        "toolset",
        "toolset_membership",
        "invocation_profile",
        "step_assignment",
        # CR-7 closed-enumeration storage (G-001/T-003): enumeration and value
        # records are entities with immutable ref identities of their own.
        "enumeration",
        "enumeration_value",
    }
)

EXCLUDED_TABLES: dict[str, str] = {
    "step_runtime": (
        "Keyed by step_uuid rather than an identity of its own; the row is an "
        "attribute bag of its parent step and is removed by ON DELETE CASCADE."
    ),
    "command_metric": (
        "Append-only timing log with no update path and no soft delete; rows "
        "are measurements, not entities that can be referenced."
    ),
    "embedding_cache": (
        "Content-addressed cache keyed by content_hash; the uuid is an "
        "artifact of the table shape and identifies no domain object."
    ),
    "entity_identity": (
        "The registry itself. Registering the registry in the registry would "
        "be circular."
    ),
    "reference_field": (
        "CR-7 protected field catalogue (0027): a field record is catalogue "
        "metadata keyed by property name, ensured by CRUD and deletable only "
        "under schema-update admission; it is not a referenceable entity."
    ),
    "relation_index": (
        "CR-7 derived relation index (0027): immutable source-target-field "
        "triples projected from canonical columns; atomically replaceable by "
        "rebuild and therefore never an identity-bearing entity table."
    ),
}
"""Tables deliberately outside the identity registry, each with its reason.

Membership here is a documented decision, not an oversight. A table that is
neither in ALLOWED_TABLES nor in EXCLUDED_TABLES is an unclassified gap.
"""

SCOPED_NAME_TABLES = frozenset(
    {
        "plan",
        "paragraph",
        "concept",
        "relation",
        "step",
        "node_version",
        "revision",
        "ref",
    }
)
"""Tables resolve_scoped_name may query.

This is deliberately narrower than ALLOWED_TABLES and is not the registry
scope. resolve_scoped_name interpolates the table name into a query that
filters on plan_uuid, so only plan-scoped truth tables can serve it; the
runtime-overlay and agent-configuration tables carry no plan_uuid column at
all. Widening the registry must not widen this allowlist.
"""

ALLOWED_NAME_COLUMNS = frozenset({"concept_id", "step_id", "label", "name"})

RESERVED_KIND = "project_reservation"
"""The entity_identity.kind value marking a planning-time namespace reservation.

A reservation occupies an identifier without any local row existing for it, so
that a future external project UUID cannot collide with an entity, a plan, or
another reservation.
"""

ENTITY_KIND = "entity"
"""The entity_identity.kind value for an ordinary registered entity row."""


def register_entity_identity(
    conn: psycopg.Connection,
    *,
    entity_id: uuid.UUID,
    table_name: str,
    entity_type: str,
    created_at: datetime | None = None,
) -> None:
    """Record the global UUID-to-table mapping for one entity row.

    TRANSACTION INVARIANT: this function MUST be called inside the same
    database transaction as the INSERT of the entity row it describes, and it
    never commits. A registry row that outlives a rolled-back entity INSERT
    would permanently occupy an identifier that no entity owns, and every
    later create carrying that identifier would be refused by
    ensure_identity_available with no way to diagnose the phantom.

    The INSERT keeps ON CONFLICT (id) DO NOTHING so that re-registering an
    already-registered id is idempotent rather than fatal. That clause is NOT
    the collision guard: it is silent by design. Callers that must reject a
    duplicate identifier call ensure_identity_available first.
    """
    conn.execute(
        "INSERT INTO entity_identity (id, table_name, entity_type, created_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (entity_id, table_name, entity_type, created_at or datetime.now(timezone.utc)),
    )


def ensure_identity_available(conn: psycopg.Connection, entity_id: uuid.UUID) -> None:
    """Refuse an identifier that is already registered for ANY kind.

    This is the single cross-kind collision guard of the identity registry. No
    store re-implements the check: every create path calls this before
    inserting its row, inside the same transaction, so that a duplicate
    identifier fails deterministically and leaves no partial row behind.

    Parameters:
        conn: psycopg.Connection
            An open psycopg 3 connection, inside the caller's transaction.
        entity_id: uuid.UUID
            The identifier the caller intends to claim.

    Returns:
        None
            When the identifier is free.

    Raises:
        plan_manager.storage.errors.DuplicateNameError
            When the identifier is already registered, for an entity of any
            kind or for a namespace reservation. The message is deterministic:
            'entity id already registered: {id} (kind={kind}, table={table})'.
    """
    row = conn.execute(
        "SELECT kind, table_name FROM entity_identity WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if row is None:
        return
    raise DuplicateNameError(
        f"entity id already registered: {entity_id} (kind={row[0]}, table={row[1]})"
    )


def reserve_project_uuid(
    conn: psycopg.Connection,
    project_uuid: uuid.UUID,
    reserved_by: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Claim a future external project UUID as a namespace reservation.

    The reservation is recorded in the identity registry under RESERVED_KIND.
    No local row is created for it anywhere: external project identifiers stay
    external, and this only prevents a later entity, plan, or reservation from
    taking the same identifier.

    Raises:
        plan_manager.storage.errors.DuplicateNameError
            When the identifier is already taken, via ensure_identity_available.
    """
    ensure_identity_available(conn, project_uuid)
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO entity_identity "
        "(id, table_name, entity_type, kind, reserved_by, note, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            project_uuid,
            "",
            RESERVED_KIND,
            RESERVED_KIND,
            reserved_by,
            note,
            created_at,
        ),
    )
    return {
        "id": project_uuid,
        "project_uuid": project_uuid,
        "kind": RESERVED_KIND,
        "reserved_by": reserved_by,
        "note": note,
        "created_at": created_at,
    }


def release_project_reservation(conn: psycopg.Connection, project_uuid: uuid.UUID) -> None:
    """Release a namespace reservation, freeing the identifier again.

    Only a reservation is released. A registered entity identifier is never
    removed by this function, so a mistyped uuid cannot orphan a live row.

    Raises:
        plan_manager.storage.errors.NotFoundError
            When no reservation exists for the given identifier.
    """
    row = conn.execute(
        "DELETE FROM entity_identity WHERE id = %s AND kind = %s RETURNING id",
        (project_uuid, RESERVED_KIND),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"project uuid reservation not found: {project_uuid}")


def unregister_entity_identity(conn: psycopg.Connection, entity_id: uuid.UUID) -> None:
    """Remove one global identity mapping after the entity row is physically deleted."""
    conn.execute("DELETE FROM entity_identity WHERE id = %s", (entity_id,))


def resolve_entity_identity(conn: psycopg.Connection, entity_id: uuid.UUID) -> dict[str, Any]:
    """Resolve an entity UUID to its registered table, entity type, and kind.

    Namespace reservations resolve here too, reported with kind=RESERVED_KIND
    and a populated reserved_by, so a caller can tell a claimed-but-uncreated
    identifier apart from a live entity.
    """
    row = conn.execute(
        "SELECT id, table_name, entity_type, kind, reserved_by, note, created_at "
        "FROM entity_identity WHERE id = %s",
        (entity_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"entity identity not found: {entity_id}")
    return {
        "id": row[0],
        "table_name": row[1],
        "entity_type": row[2],
        "kind": row[3],
        "reserved_by": row[4],
        "note": row[5],
        "created_at": row[6],
    }


def resolve_entity_identities_batch(
    conn: psycopg.Connection, ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Resolve many entity UUIDs to their registered table/entity_type in one query.

    Unlike resolve_entity_identity, this never raises: ids with no
    entity_identity row are simply absent from the returned mapping. Used by
    callers (e.g. cascade_preview's detail projection, todo 3c762bfe) that
    classify a bounded batch of entity_uuids without one round trip per id.

    Parameters:
        conn: psycopg.Connection
            An open psycopg 3 connection.
        ids: list[uuid.UUID]
            The entity UUIDs to resolve. An empty list short-circuits to an
            empty dict without issuing a query.

    Returns:
        dict[uuid.UUID, dict[str, Any]]
            Mapping from each resolvable id to its
            {"id", "table_name", "entity_type", "created_at"} dict.
    """
    if not ids:
        return {}
    rows = conn.execute(
        "SELECT id, table_name, entity_type, created_at FROM entity_identity WHERE id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    return {
        row[0]: {"id": row[0], "table_name": row[1], "entity_type": row[2], "created_at": row[3]}
        for row in rows
    }


def resolve_scoped_name(
    conn: psycopg.Connection,
    table: str,
    plan_uuid: uuid.UUID,
    name_column: str,
    name: str,
) -> uuid.UUID:
    """Resolve a human-readable scoped name to its immutable entity UUID.

    ``table`` must be in SCOPED_NAME_TABLES and ``name_column`` in
    ALLOWED_NAME_COLUMNS; both are checked BEFORE any value reaches string
    interpolation, else ValueError. The lookup is scoped to ``plan_uuid``
    (e.g. concept_id/step_id/label/name) and returns the row's uuid.

    Raises:
        ValueError: on an allowlist miss, before any SQL executes.
        plan_manager.storage.errors.NotFoundError: when no row matches.
    """
    if table not in SCOPED_NAME_TABLES:
        raise ValueError(f"table not allowed: {table!r}")
    if name_column not in ALLOWED_NAME_COLUMNS:
        raise ValueError(f"name_column not allowed: {name_column!r}")
    sql = f"SELECT uuid FROM {table} WHERE plan_uuid = %s AND {name_column} = %s"
    row = conn.execute(sql, (plan_uuid, name)).fetchone()
    if row is None:
        raise NotFoundError(
            f"{table}.{name_column}={name!r} not found for plan {plan_uuid}"
        )
    return row[0]


# CR-7 G-001/T-001/A-001 helper surface. The v4 validation rule and the
# registry audit/rebuild helpers live in identity_audit (the 400-line
# file budget of this module forced the split); they remain importable
# from here as the contract surface.
from plan_manager.storage.identity_audit import (  # noqa: E402,F401
    PRIMARY_KEY_COLUMNS,
    audit_registry,
    ensure_v4_entity_uuid,
    remove_extra_identity_if_unreferenced,
    restore_missing_identities,
)
