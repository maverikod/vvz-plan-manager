"""Persistence functions for the Relation domain entity (MRS concept
C-004).


This function writes Relation rows in table `relation`, scoped to one
plan via the plan_uuid column. Field validation and endpoint-existence
checks are delegated to plan_manager.domain.relation before any row is
written.

"""


import uuid

import psycopg

from plan_manager.domain.relation import Relation, validate_relation, check_relation_endpoints_exist
from plan_manager.domain.concept_store import list_concept_ids


def insert_relation(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, relation: Relation
) -> uuid.UUID:
    """Validate and insert a new Relation row scoped to one plan.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        relation: The Relation instance to persist.

    Returns:
        The generated uuid primary identity of the inserted row.

    Raises:
        RelationValidationError: propagated unmodified from
            validate_relation or check_relation_endpoints_exist if
            relation fails field validation or either endpoint is not
            among the plan's existing concept_id values.
    """
    validate_relation(relation)
    check_relation_endpoints_exist(relation, list_concept_ids(conn, plan_uuid))
    row_uuid = uuid.uuid4()
    # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
    # engine's creation path; this module no longer composes INSERT SQL.
    Relation.crud_create(
        conn,
        {
            "uuid": row_uuid,
            "plan_uuid": plan_uuid,
            "from_concept": relation.from_concept,
            "to_concept": relation.to_concept,
            "type": relation.type,
        },
        returning=False,
    )
    return row_uuid


def list_relations(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> list[tuple[str, str, str]]:
    """List every (from_concept, to_concept, type) triple for one plan.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.

    Returns:
        List of (from_concept, to_concept, type) tuples for the given
        plan_uuid, ordered ascending by (from_concept, to_concept, type).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT from_concept, to_concept, type FROM relation "
            "WHERE plan_uuid = %s ORDER BY from_concept, to_concept, type",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [(row[0], row[1], row[2]) for row in rows]



def remove_relation(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    from_concept: str,
    to_concept: str,
    type: str,
) -> uuid.UUID:
    """Delete the Relation row matching from_concept, to_concept, and type.

    Note: the parameter named `type` shadows the Python builtin `type`;
    this is kept because it matches the domain vocabulary (Relation.type
    in plan_manager.domain.relation).

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        from_concept: concept_id of the source concept.
        to_concept: concept_id of the target concept.
        type: Relation type of the row to delete.

    Returns:
        The uuid primary identity of the deleted row.

    Raises:
        ValueError: If no row matches all three of from_concept,
            to_concept, and type for the given plan_uuid (message is
            exactly "relation not found").
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid FROM relation WHERE plan_uuid = %s AND from_concept = %s "
            "AND to_concept = %s AND type = %s",
            (plan_uuid, from_concept, to_concept, type),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("relation not found")
    row_uuid = row[0]
    # CR-7 G-004 compatibility note: bug 9efa5ec5 - the guarded engine wrapper's
    # audit write cannot carry relation's composite (plan_uuid, from_concept,
    # to_concept, type) identity into runtime_audit_log.entity_id, which is
    # NOT NULL on live PG and has no non-UUID representation; routing this
    # DELETE through crud_hard_delete crashed the whole operation there.
    # Reverted to the raw statement until the c315ff84 guard rework adds
    # composite-identity audit support.
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM relation WHERE plan_uuid = %s AND from_concept = %s "
            "AND to_concept = %s AND type = %s",
            (plan_uuid, from_concept, to_concept, type),
        )
    return row_uuid


def update_relation(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    from_concept: str,
    to_concept: str,
    type: str,
    new_type: str,
) -> uuid.UUID:
    """Update the type of an existing Relation row matching from_concept, to_concept, and type.

    Note: the parameters named `type` and `new_type` identify, respectively, the
    relation's current type (used to locate the row) and its replacement type
    (written to the row). `type` shadows the Python builtin `type`; this is kept
    because it matches the domain vocabulary (Relation.type in
    plan_manager.domain.relation).

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        from_concept: concept_id of the source concept.
        to_concept: concept_id of the target concept.
        type: current Relation type of the row to update.
        new_type: Relation type to write in place of type.

    Returns:
        The uuid primary identity of the updated row.

    Raises:
        RelationValidationError: propagated unmodified from validate_relation if
            new_type is not one of RELATION_TYPES, or if from_concept or
            to_concept do not match CONCEPT_ID_PATTERN.
        ValueError: If no row matches all three of from_concept, to_concept,
            and type for the given plan_uuid (message is exactly "relation not
            found").
    """
    validate_relation(Relation(from_concept=from_concept, to_concept=to_concept, type=new_type))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid FROM relation WHERE plan_uuid = %s AND from_concept = %s "
            "AND to_concept = %s AND type = %s",
            (plan_uuid, from_concept, to_concept, type),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError("relation not found")
    row_uuid = row[0]
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE relation SET type = %s WHERE uuid = %s",
            (new_type, row_uuid),
        )
    return row_uuid
