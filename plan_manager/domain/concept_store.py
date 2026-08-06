"""Persistence functions for the Concept domain entity (MRS concept
C-003).

These functions write and read Concept rows in table `concept`, scoped
to one plan via the plan_uuid column. Field validation and concept_id
uniqueness checks are delegated to plan_manager.domain.concept before any
row is written.

"""

import uuid

import psycopg

from plan_manager.domain.concept import Concept, validate_concept, check_concept_id_unique


class _ConceptRowByUuid(Concept):
    """Uuid-keyed deletion seat for the concept table (CR-7 G-004).

    The guard's catalog probes for concept are keyed by concept_id (the
    scoped reference key), while the physical row is deleted by its uuid.
    remove_concept consults the guard's read surface with the concept_id
    first, then hands the uuid to the guarded engine delete; this subclass
    only narrows the identity predicate to the uuid column.
    """

    # Not a user-facing entity type of its own: ENTITY_TYPE=None keeps this
    # seat out of the catalog's entity-type resolver ("concept" stays claimed
    # by exactly one class); the guard call names the audit type explicitly.
    ENTITY_TYPE = None
    ID_COLUMN = "uuid"
    ID_COLUMNS = ()


def list_concept_ids(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> list[str]:
    """List all concept_id values stored for one plan, ordered by concept_id.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.

    Returns:
        List of concept_id strings from table concept where the
        plan_uuid column equals the given plan_uuid, ordered ascending
        by concept_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT concept_id FROM concept WHERE plan_uuid = %s ORDER BY concept_id",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [row[0] for row in rows]


def insert_concept(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, concept: Concept
) -> uuid.UUID:
    """Validate and insert a new Concept row scoped to one plan.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        concept: The Concept instance to persist.

    Returns:
        The generated uuid primary identity of the inserted row.

    Raises:
        ConceptValidationError: propagated unmodified from
            validate_concept or check_concept_id_unique if concept fails
            field validation or its concept_id is already present among
            the plan's existing concept_id values.
    """
    validate_concept(concept)
    check_concept_id_unique(concept.concept_id, list_concept_ids(conn, plan_uuid))
    row_uuid = uuid.uuid4()
    # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
    # engine's creation path; this module no longer composes INSERT SQL.
    Concept.crud_create(
        conn,
        {
            "uuid": row_uuid,
            "plan_uuid": plan_uuid,
            "concept_id": concept.concept_id,
            "name": concept.name,
            "definition": concept.definition,
            "properties": concept.properties,
            "source_labels": concept.source_labels,
        },
        returning=False,
    )
    return row_uuid


def get_concept(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, concept_id: str
) -> Concept | None:
    """Fetch one full Concept row by concept_id within one plan.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        concept_id: The concept_id to look up.

    Returns:
        The matching Concept, or None if no row with this concept_id
        exists for the given plan_uuid.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT concept_id, name, definition, properties, source_labels "
            "FROM concept WHERE plan_uuid = %s AND concept_id = %s",
            (plan_uuid, concept_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return Concept(
        concept_id=row[0],
        name=row[1],
        definition=row[2],
        properties=row[3],
        source_labels=row[4],
    )


def list_concepts(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> list[Concept]:
    """List all full Concept rows for one plan, ordered by concept_id.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.

    Returns:
        List of Concept instances for the given plan_uuid, ordered
        ascending by concept_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT concept_id, name, definition, properties, source_labels "
            "FROM concept WHERE plan_uuid = %s ORDER BY concept_id",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    return [
        Concept(
            concept_id=row[0],
            name=row[1],
            definition=row[2],
            properties=row[3],
            source_labels=row[4],
        )
        for row in rows
    ]


def update_concept(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    concept_id: str,
    fields: dict,
) -> Concept:
    """Update selected fields of an existing Concept row.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        concept_id: concept_id of the row to update.
        fields: Mapping of field names to new values. Allowed keys are
            exactly "name", "definition", "properties", "source_labels".

    Returns:
        The updated Concept, re-read from the database after the UPDATE.

    Raises:
        ValueError: If fields contains a key other than "name",
            "definition", "properties", "source_labels" (message is
            f"unknown field: {key}" naming the offending key), or if no
            row with this concept_id exists for the given plan_uuid
            (message is f"concept not found: {concept_id}").
        ConceptValidationError: propagated unmodified from
            validate_concept if the merged Concept (the existing row
            with the touched fields replaced) fails field validation.
    """
    allowed_fields = {"name", "definition", "properties", "source_labels"}
    for key in fields:
        if key not in allowed_fields:
            raise ValueError(f"unknown field: {key}")
    existing = get_concept(conn, plan_uuid, concept_id)
    if existing is None:
        raise ValueError(f"concept not found: {concept_id}")
    merged = Concept(
        concept_id=existing.concept_id,
        name=fields.get("name", existing.name),
        definition=fields.get("definition", existing.definition),
        properties=fields.get("properties", existing.properties),
        source_labels=fields.get("source_labels", existing.source_labels),
    )
    validate_concept(merged)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE concept SET name = %s, definition = %s, properties = %s, "
            "source_labels = %s WHERE plan_uuid = %s AND concept_id = %s",
            (
                merged.name,
                merged.definition,
                merged.properties,
                merged.source_labels,
                plan_uuid,
                concept_id,
            ),
        )
    return get_concept(conn, plan_uuid, concept_id)



def remove_concept(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, concept_id: str
) -> Concept:
    """Delete a Concept row and return the pre-delete row.

    Args:
        conn: Open psycopg database connection.
        plan_uuid: UUID of the owning plan.
        concept_id: concept_id of the row to delete.

    Returns:
        The Concept row exactly as it existed immediately before
        deletion.

    Raises:
        ValueError: If no row with this concept_id exists for this
            plan_uuid (message is f"concept not found: {concept_id}").
    """
    existing = get_concept(conn, plan_uuid, concept_id)
    if existing is None:
        raise ValueError(f"concept not found: {concept_id}")
    # CR-7 G-004 (C-005, C-012): the deletion guard is consulted on every
    # concept removal (bug da06315d: a concept still referenced by relations
    # is refused). The catalog keys concept references by concept_id, so the
    # guard's read surface is probed with that key; the physical delete then
    # goes through the guarded engine wrapper on the row's uuid.
    from plan_manager.domain.entity import EntityReferencedError
    from plan_manager.storage.hard_delete_guard import lookup_referrers

    referrers = [
        ref
        for ref in lookup_referrers(conn, "concept", concept_id)
        if not (ref["table"] == "relation" and plan_uuid is None)
    ]
    if referrers:
        raise EntityReferencedError("concept", concept_id, referrers)
    row = conn.execute(
        "SELECT uuid FROM concept WHERE plan_uuid = %s AND concept_id = %s",
        (plan_uuid, concept_id),
    ).fetchone()
    _ConceptRowByUuid.crud_hard_delete(
        conn,
        row[0],
        require_soft_deleted=False,
        returning=False,
        plan_uuid=plan_uuid,
        audit_entity_type="concept",
    )
    return existing
