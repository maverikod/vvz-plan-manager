"""Central reference-aware hard deletion (C-011).

Two surfaces, deliberately kept apart:

* :func:`lookup_referrers` builds and runs only SELECTs. It is safe to call for
  its own sake, which is what the reference-inspection command does.
* :func:`guarded_hard_delete` composes the DELETE. It consults the lookup first
  and refuses while any blocking reference exists.

Splitting them is the point of C-011: the read that decides whether a deletion
is allowed must be reusable without carrying the write that performs it.

This module is also the SINGLE place hard deletions are audited — both the
refusal and the removal. Callers must not add their own audit write on top, or
one deletion produces two records.

Only BLOCKING references refuse a deletion. A reference the database removes
itself via ON DELETE CASCADE is catalogued but does not block: treating it as
blocking would refuse deletions that succeed today, since a plan delete cascades
to its paragraphs, concepts, relations and steps.
"""

from __future__ import annotations

import uuid as uuid_module
from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import sql

from plan_manager.storage.reference_catalog import blocking_entries_targeting

_NO_PROBE = object()
"""Sentinel: this catalog entry cannot be probed with the given identity."""


def _probe_value(identity: Any, target_column: str) -> Any:
    """Resolve the scalar to bind against one catalog entry's source column.

    ``identity`` is almost always a bare scalar -- the ordinary uuid-keyed
    case -- and is forwarded unchanged, exactly as before bug c315ff84: the
    catalog's ``target_column`` default ("uuid") does not have to match the
    dataclass field name (bug_uuid, fix_uuid, ...; see reference_catalog's
    TARGET-COLUMN CAVEAT), so name-matching a scalar identity would break
    every one of those.

    ``identity`` is a mapping only for a genuinely composite ID_COLUMNS
    identity (e.g. Concept's plan_uuid+concept_id) or when a caller passes an
    explicit multi-key probe override. There, forwarding the mapping itself
    as a SQL parameter cannot bind (bug c315ff84 shape 1: psycopg raises), and
    probing a scoped key such as concept_id with the wrong component silently
    matches nothing (shape 2). The component named by the catalog's own
    ``target_column`` is the only correct choice; a single-key mapping falls
    back to its sole value for the same reason the scalar branch ignores the
    catalog's column name.
    """
    if isinstance(identity, Mapping):
        if target_column in identity:
            return identity[target_column]
        if len(identity) == 1:
            return next(iter(identity.values()))
        return _NO_PROBE
    return identity


def _json_safe(value: Any) -> Any:
    """Render a value so it survives the audit store's Jsonb adapter.

    record_runtime_change wraps changed_fields in Jsonb, which cannot encode a
    uuid. An unconverted identifier raises at the moment of the audit write and
    turns a correct refusal into a crash, so every id is stringified here.
    """
    if isinstance(value, uuid_module.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def lookup_referrers(
    conn: psycopg.Connection, table: str, entity_id: Any
) -> list[dict[str, Any]]:
    """List the live rows that reference one entity and would block its removal.

    Args:
        conn: open connection, inside the caller's transaction.
        table: the real DB TABLE NAME, matching ``CatalogEntry.target_table``.
            A caller holding a user-facing entity type converts it first with
            the catalog's ``table_name_for_entity_type``; this function never
            accepts an entity type. Passing one would match no catalog entry and
            return an empty list, which reads as "nothing blocks this deletion"
            while the truth is the opposite.
        entity_id: the identifier being probed for. Usually a bare scalar
            (the uuid-keyed case). For a composite identity -- or an explicit
            multi-key probe override -- pass a mapping of id-column name to
            value; each catalog entry is then probed with the component named
            by its own ``target_column`` (see :func:`_probe_value`), never
            with the mapping itself, which cannot bind as a SQL parameter.

    Returns:
        One dict per referring row with keys ``table``, ``column``,
        ``referrer_id`` and ``referrer_kind``; ``referrer_kind`` is the source
        table name. Empty when nothing blocks.
    """
    referrers: list[dict[str, Any]] = []
    for entry in blocking_entries_targeting(table):
        probe_value = _probe_value(entity_id, entry.target_column)
        if probe_value is _NO_PROBE:
            # A composite identity that does not carry the component this
            # entry's target_column names cannot be probed at all -- there is
            # no value to bind. Skipping (rather than guessing) is the safe
            # choice: no other catalog entry loses its own probe over this.
            continue

        clauses: list[sql.Composable] = []
        params: list[Any] = []

        if entry.array:
            clauses.append(sql.SQL("{} @> ARRAY[%s]").format(sql.Identifier(entry.source_column)))
        else:
            clauses.append(sql.SQL("{} = %s").format(sql.Identifier(entry.source_column)))
        params.append(probe_value)

        # A polymorphic column such as anchor_ref_id points at a different table
        # per discriminator value, so the const filter is what selects THIS
        # target. Without it the probe matches rows anchored to another kind.
        for column, literal in entry.const_filters:
            clauses.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
            params.append(literal)

        # A scoped reference (concept) is only a reference within the same plan.
        for source_column, _target_column in entry.scope_columns:
            clauses.append(sql.SQL("{} IS NOT NULL").format(sql.Identifier(source_column)))

        if entry.live_column is not None:
            clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(entry.live_column)))

        query = sql.SQL("SELECT uuid FROM {} WHERE {}").format(
            sql.Identifier(entry.source_table),
            sql.SQL(" AND ").join(clauses),
        )
        for row in conn.execute(query, params).fetchall():
            referrers.append(
                {
                    "table": entry.source_table,
                    "column": entry.source_column,
                    "referrer_id": row[0],
                    "referrer_kind": entry.source_table,
                }
            )
    return referrers


def guarded_hard_delete(
    conn: psycopg.Connection,
    entity_cls: type,
    entity_id: Any,
    *,
    changed_by: str = "system",
    returning: bool = True,
    require_soft_deleted: bool = True,
    plan_uuid: Any = None,
    audit_entity_type: str | None = None,
    probe_id: Any = None,
) -> dict[str, Any] | None:
    """Physically remove one row, refusing while any blocking reference exists.

    The entity CLASS is taken rather than a bare table name, because the full
    contract this replaces is class-dependent: the soft-delete precondition, the
    RETURNING projection, the composite-key predicate, and identity
    unregistration all come from the class. The catalog lookup uses
    ``entity_cls.TABLE_NAME``.

    Args:
        changed_by: actor recorded in the audit trail. Defaulted so that every
            pre-existing caller keeps working; callers that know the actor pass
            it so the record is attributable.
        plan_uuid: the plan the removal is anchored to, when the caller knows it.
            The guard cannot derive it — the anchor column differs per entity
            (anchor_plan_uuid, source_plan_uuid, target_plan_uuid,
            linked_plan_uuid) — so a caller that has already read the row passes
            it, and the audit row keeps the plan anchoring it had before this
            centralization.
        audit_entity_type: the entity_type value to record, when it must differ
            from entity_cls.entity_type(). Two shipped wrappers historically
            recorded the TABLE name (runtime_comment, bug_report) rather than the
            entity type (comment, bug). Changing them would split the audit
            history for existing audit_list queries, so those callers pass their
            historical value. Also reported as the ``entity_type`` of a raised
            EntityReferencedError, for the same reason.
        probe_id: the identity to consult the reference catalog with, when it
            differs from ``entity_id`` (bug c315ff84). Defaults to
            ``entity_id``, which is correct for every ordinary uuid-keyed and
            composite-keyed entity. It exists for a deletion SEAT class whose
            own identity is not what the catalog keys its blocking entries by
            -- e.g. concept_store's ``_ConceptRowByUuid`` deletes by uuid, but
            the catalog's entries for "concept" key on the scoped
            ``concept_id`` (see ``reference_catalog``'s "references to concept"
            entries) -- so the caller passes the scoped key explicitly rather
            than the guard silently matching nothing against the wrong column.
            Also reported as the ``entity_id`` of a raised EntityReferencedError
            and its refusal-audit payload, since that is the identity the
            refusal was actually decided against.
        returning: when False the deleted payload is not read back and None is
            returned, exactly as before.
        require_soft_deleted: keep the two-phase discipline — a row is removed
            only after it has been soft-deleted.

    Raises:
        NotImplementedError: the entity opts out of soft delete entirely and so
            cannot be purged through this path.
        EntityNotSoftDeletedError: the row is still live.
        EntityReferencedError: a blocking reference exists. A refusal audit is
            written first, so a blocked deletion is no longer invisible.
    """
    # Imported inside the function: the entity module imports this guard's
    # errors, so a module-level import would close a cycle. The cycle is
    # deliberate — the guard owns the deletion, the entity module owns the error
    # type — and this is where it is resolved.
    from plan_manager.domain.entity import (
        EntityNotSoftDeletedError,
        EntityReferencedError,
        unregister_entity_identity,
    )
    from plan_manager.storage.runtime_audit_store import record_runtime_change

    if require_soft_deleted:
        if entity_cls.SOFT_DELETE_COLUMN is None:
            raise NotImplementedError(
                f"{entity_cls.__name__} cannot be purged through soft-delete batch semantics"
            )
        current = entity_cls.get_by_id(conn, entity_id, include_deleted=True)
        if current is None:
            return None
        if current.get(entity_cls.SOFT_DELETE_COLUMN) is None:
            raise EntityNotSoftDeletedError(entity_cls.entity_type(), entity_id)

    reported_id = entity_id if probe_id is None else probe_id
    referrers = lookup_referrers(conn, entity_cls.TABLE_NAME, reported_id)
    if referrers:
        record_runtime_change(
            conn,
            plan_uuid=plan_uuid,
            entity_type=audit_entity_type or entity_cls.entity_type(),
            entity_id=entity_id if isinstance(entity_id, uuid_module.UUID) else None,
            action="hard_delete",
            changed_by=changed_by,
            changed_fields=_json_safe(
                {"refused": True, "id": reported_id, "referrers": referrers}
            ),
        )
        raise EntityReferencedError(
            audit_entity_type or entity_cls.entity_type(), reported_id, referrers
        )

    id_values = entity_cls._normalize_id(entity_id)
    predicate, params = entity_cls._predicate_sql(id_values)
    # The DELETE is composed here, structurally separate from every SELECT the
    # lookup above builds.
    query = sql.SQL("DELETE FROM {} WHERE {}").format(entity_cls._table(), predicate)
    if returning:
        query += sql.SQL(" RETURNING {}").format(entity_cls._select_columns_sql())
    cur = conn.execute(query, params)

    deleted: dict[str, Any] | None = None
    if returning:
        row = cur.fetchone()
        if row is None:
            return None
        deleted = entity_cls._row_to_dict(cur, row)

    if entity_cls.REGISTER_IDENTITY and len(id_values) == 1:
        only_id = next(iter(id_values.values()))
        if isinstance(only_id, uuid_module.UUID):
            unregister_entity_identity(conn, only_id)

    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type=audit_entity_type or entity_cls.entity_type(),
        entity_id=entity_id if isinstance(entity_id, uuid_module.UUID) else None,
        action="hard_delete",
        changed_by=changed_by,
        changed_fields=_json_safe({"id": entity_id}),
    )
    return deleted
