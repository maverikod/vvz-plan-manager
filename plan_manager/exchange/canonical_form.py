"""Canonical serialized form for the plan-manager exchange document (CR-7).

CR-7 G-005/T-001/A-001. This module defines the target-schema shape ONE time,
in the target-schema shape described by C-006/C-002/C-003 rather than the
current live-table shape: every entity record carries ``ref``, ``entity_kind``,
``owner``, ``markdel``, ``created_at``/``updated_at`` and the entity's own
domain properties; relation triples (source ref, target ref, field ref) form a
separate, semantically unordered section that mirrors
:mod:`plan_manager.storage.relation_index_store`'s ``Triple`` shape; the
document envelope adds a format version and a checksum computed over the
exact serialized bytes of its content.

Everything here is driven by the closed entity registry -- the
``DataclassEntity`` subclasses discovered by
:func:`plan_manager.storage.reference_catalog._entity_classes`, imported and
reused (not copied) so this module and the catalog can never disagree about
what entity kinds exist. There is no per-entity-kind branch anywhere in this
module: every entity is read through its own descriptor ClassVars (``COLUMNS``,
``ID_COLUMN``, ``OWNER_COLUMN``/``OWNER_ROOT``/``OWNER_GAP``,
``SOFT_DELETE_COLUMN``, ``CREATED_AT_COLUMN``, ``UPDATED_AT_COLUMN``).

``markdel`` is the marked/deleted flag concept for the target schema, where a
boolean column replaces today's ``deleted_at`` timestamp. This module derives
it from ``SOFT_DELETE_COLUMN`` presence/value (a non-NULL value on the current
schema means the row is marked): ``markdel`` is True exactly when the entity
declares a ``SOFT_DELETE_COLUMN`` and that column's value on the row is not
None. Because ``markdel`` is a boolean while the live column is a timestamp,
translating a canonical record back to an entity row cannot reconstruct the
original deletion instant -- only the marked/not-marked state survives the
round trip. That loss is intentional and confined to this one column: it is
the schema-shape difference this module is anticipating, not a defect.

Scope. This module only transforms already-fetched rows (plain mappings) and
already-computed relation triples into the canonical shape and back, and
computes/verifies the checksum over that shape. It never opens a database
connection and never queries one. The exporter/importer wiring that fetches
rows, the DDL for a target-schema table, and any cutover mechanics are sibling
and later steps' business, not this one's.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any

# Read-only consumption of the catalog's entity discovery: importing
# `_entity_classes` reuses the single walk that already keeps the reference
# catalog's own type enumerations honest, instead of a second, divergent walk
# living here. `resolve_entity_class` is the sanctioned entity_kind -> class
# resolver used by the reverse (canonical record -> entity row) direction.
from plan_manager.storage.reference_catalog import (
    _entity_classes as _catalog_entity_classes,
    resolve_entity_class,
)

FORMAT_VERSION = 1
"""Canonical document format version. Bump on any change to the shape below."""

RelationTriple = tuple[Any, Any, Any]
"""(source_ref, target_ref, field_ref) -- matches relation_index_store.Triple.

Values may be uuid.UUID or an already-canonical str; both are accepted and
normalized by :func:`_canonicalize_scalar`.
"""


def registered_entity_classes() -> list[type]:
    """Every DataclassEntity subclass the closed entity registry knows.

    A thin, named wrapper around the catalog's own discovery walk so callers
    of this module do not need to know the catalog's private helper exists.
    """
    return _catalog_entity_classes()


# --------------------------------------------------------------------------
# Scalar canonicalization: turn Python values into exactly-repeatable,
# JSON-safe values so that equal content always produces equal bytes.
# --------------------------------------------------------------------------


def _canonicalize_scalar(value: Any) -> Any:
    """Render one value into its canonical, JSON-safe representation.

    uuid.UUID -> str(value); datetime/date -> isoformat(); mappings and
    sequences are canonicalized element-wise (dict keys are stringified so
    json.dumps never raises on a non-str key); every other value passes
    through unchanged (it must already be JSON-safe: str, int, float, bool,
    or None).
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonicalize_scalar(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonicalize_scalar(item) for item in value]
    return value


# --------------------------------------------------------------------------
# (1) Serializers: entity row <-> canonical record, driven by the descriptor.
# --------------------------------------------------------------------------


def _entity_ref_column(entity_cls: type) -> str:
    """Resolve the single scalar column this entity's canonical ``ref`` reads.

    Every entity in the closed registry either carries a genuine ``uuid``
    column (the CR-7 target identity, including concept/relation, whose
    ``ID_COLUMN``/``ID_COLUMNS`` still name their legacy composite business
    key for CRUD addressing) or -- for the one documented exception,
    step_runtime, which is keyed by its owning step's uuid and carries no
    identity of its own -- declares a single ``ID_COLUMN``. Preferring
    ``uuid`` first is what lets a composite-keyed entity like concept or
    relation still get a proper singular ref.
    """
    columns = set(entity_cls.COLUMNS)
    if "uuid" in columns:
        return "uuid"
    if entity_cls.ID_COLUMN is not None:
        return entity_cls.ID_COLUMN
    raise ValueError(
        f"{entity_cls.__name__}: no 'uuid' column and no single ID_COLUMN; "
        "canonical form requires exactly one scalar ref column per entity row"
    )


def _owner_column(entity_cls: type) -> str | None:
    """The owning-reference column name, or None for a root/gap declaration.

    OWNER_ROOT and OWNER_GAP both mean "this record's owner field is None":
    a root has no owner by design, and a gap is a recorded absence of a
    usable owner column. The distinction between the two is metadata about
    the entity KIND (available from the registry itself), not something a
    per-record canonical form needs to carry a second time.
    """
    return entity_cls.OWNER_COLUMN


def entity_row_to_canonical_record(entity_cls: type, row: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize one fetched entity row into the canonical record shape.

    Args:
        entity_cls: A DataclassEntity subclass from the closed registry
            (typically one returned by :func:`registered_entity_classes`).
        row: A mapping keyed by this entity's live column names, e.g. the
            dict shape returned by DataclassEntity.crud_get/crud_list.

    Returns:
        {"ref", "entity_kind", "owner", "markdel", "created_at", "updated_at",
        "properties"} -- every value already canonicalized (JSON-safe), and
        "properties" holding every declared column not otherwise accounted
        for, sorted by column name for deterministic bytes.
    """
    ref_column = _entity_ref_column(entity_cls)
    owner_column = _owner_column(entity_cls)
    soft_delete_column = entity_cls.SOFT_DELETE_COLUMN
    created_at_column = entity_cls.CREATED_AT_COLUMN
    updated_at_column = entity_cls.UPDATED_AT_COLUMN

    markdel = soft_delete_column is not None and row.get(soft_delete_column) is not None

    excluded = {ref_column, owner_column, soft_delete_column, created_at_column, updated_at_column}
    excluded.discard(None)
    properties = {
        column: _canonicalize_scalar(row.get(column))
        for column in entity_cls.COLUMNS
        if column not in excluded
    }

    return {
        "ref": _canonicalize_scalar(row[ref_column]),
        "entity_kind": entity_cls.ENTITY_TYPE,
        "owner": _canonicalize_scalar(row.get(owner_column)) if owner_column else None,
        "markdel": bool(markdel),
        "created_at": _canonicalize_scalar(row.get(created_at_column)) if created_at_column else None,
        "updated_at": _canonicalize_scalar(row.get(updated_at_column)) if updated_at_column else None,
        "properties": dict(sorted(properties.items())),
    }


def canonical_record_to_entity_row(record: Mapping[str, Any]) -> tuple[type, dict[str, Any]]:
    """Reconstruct (entity_cls, row-shaped dict) from one canonical record.

    The entity kind resolves through the registry's single sanctioned
    resolver (`resolve_entity_class`), so a record naming an unknown
    ``entity_kind`` raises exactly the ValueError that resolver raises.

    The returned row is keyed by this entity's live column names, mirroring
    what `entity_row_to_canonical_record` accepted. Values are the canonical
    (already JSON-safe) forms, not rehydrated into uuid.UUID/datetime -- the
    exporter/importer wiring that owns typed persistence is a sibling step;
    this function's contract is the inverse of the forward serializer's
    field placement, not a full type round trip. The one field that is
    deliberately NOT a faithful round trip at all is the soft-delete column:
    `markdel` is a boolean, so a soft-deleted row reconstructs with that
    column set to True rather than an invented deletion timestamp.
    """
    entity_cls = resolve_entity_class(record["entity_kind"])
    ref_column = _entity_ref_column(entity_cls)
    owner_column = _owner_column(entity_cls)

    row: dict[str, Any] = dict(record.get("properties") or {})
    row[ref_column] = record["ref"]
    if owner_column is not None:
        row[owner_column] = record["owner"]
    if entity_cls.SOFT_DELETE_COLUMN is not None:
        row[entity_cls.SOFT_DELETE_COLUMN] = bool(record["markdel"])
    if entity_cls.CREATED_AT_COLUMN is not None:
        row[entity_cls.CREATED_AT_COLUMN] = record["created_at"]
    if entity_cls.UPDATED_AT_COLUMN is not None:
        row[entity_cls.UPDATED_AT_COLUMN] = record["updated_at"]
    return entity_cls, row


def build_relation_record(source_ref: Any, target_ref: Any, field_ref: Any) -> dict[str, Any]:
    """Canonicalize one (source_ref, target_ref, field_ref) triple."""
    return {
        "source_ref": _canonicalize_scalar(source_ref),
        "target_ref": _canonicalize_scalar(target_ref),
        "field_ref": _canonicalize_scalar(field_ref),
    }


# --------------------------------------------------------------------------
# (3) Document envelope: version + checksum + entities section + relations
# section, with deterministic ordering so equal content yields equal bytes.
# --------------------------------------------------------------------------


def _canonical_json_bytes(obj: Any) -> bytes:
    """The one JSON encoding this module ever produces: sorted keys, compact
    separators, ASCII-safe. Equal Python content always yields equal bytes."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def compute_checksum(payload: bytes) -> str:
    """SHA-256 hex digest of exact bytes. The sole checksum algorithm used."""
    return hashlib.sha256(payload).hexdigest()


def _document_body(
    entity_rows: Iterable[tuple[type, Mapping[str, Any]]],
    relation_triples: Iterable[RelationTriple],
) -> dict[str, Any]:
    """Build the checksummed part of the document: version + both sections.

    Entities are ordered by (entity_kind, ref) -- a total order over the
    canonicalized values, so caller-side input order never affects output
    bytes. Relations are deduplicated into a set of triples (the section is
    semantically unordered by design) and then sorted the same way, purely so
    that the semantically-unordered set has ONE deterministic byte
    projection.
    """
    records = [entity_row_to_canonical_record(cls, row) for cls, row in entity_rows]
    records.sort(key=lambda record: (record["entity_kind"], record["ref"]))

    triples = {
        (
            _canonicalize_scalar(source),
            _canonicalize_scalar(target),
            _canonicalize_scalar(field),
        )
        for source, target, field in relation_triples
    }
    relations = [
        {"source_ref": source, "target_ref": target, "field_ref": field}
        for source, target, field in sorted(triples)
    ]

    return {
        "format_version": FORMAT_VERSION,
        "entities": records,
        "relations": relations,
    }


def build_document(
    entity_rows: Iterable[tuple[type, Mapping[str, Any]]],
    relation_triples: Iterable[RelationTriple],
) -> dict[str, Any]:
    """Build the full canonical document, checksum included.

    Args:
        entity_rows: (entity_cls, row) pairs, one per entity to include. Any
            iteration order is accepted; the output is order-independent.
        relation_triples: (source_ref, target_ref, field_ref) triples, any
            iteration order, duplicates tolerated (the section is a set).

    Returns:
        {"format_version", "entities", "relations", "checksum"} where
        "checksum" is `compute_checksum` over the exact canonical bytes of
        the other three keys (never over itself).
    """
    body = _document_body(entity_rows, relation_triples)
    checksum = compute_checksum(_canonical_json_bytes(body))
    return {**body, "checksum": checksum}


def serialize_document(document: Mapping[str, Any]) -> bytes:
    """The exact bytes this document serializes to -- what a checksum covers
    when computed over the whole document, and what a transport writes."""
    return _canonical_json_bytes(document)


def parse_document(payload: bytes) -> dict[str, Any]:
    """Inverse of `serialize_document`: bytes -> document dict."""
    return json.loads(payload.decode("utf-8"))


def verify_document(document: Mapping[str, Any]) -> bool:
    """Recompute the checksum over the document's body and compare.

    True exactly when "checksum" matches `compute_checksum` of the exact
    canonical bytes of every other key. Any change to format_version,
    entities or relations -- a single differing byte in their canonical
    serialization -- changes the recomputed digest and this returns False.
    """
    body = {key: value for key, value in document.items() if key != "checksum"}
    expected = compute_checksum(_canonical_json_bytes(body))
    return expected == document.get("checksum")


# --------------------------------------------------------------------------
# (4) Semantic comparison: entities by ref + every property, relations as an
# unordered triple set. Byte equality is the checksum's concern only -- these
# helpers must treat two documents as equal when their CONTENT matches even
# if the input order (or dict key order) that produced them differed.
# --------------------------------------------------------------------------


def records_equal(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """True when two canonical records name the same entity with identical
    ref, entity_kind, owner, markdel, created_at, updated_at and properties."""
    fields = ("ref", "entity_kind", "owner", "markdel", "created_at", "updated_at", "properties")
    return all(first.get(field) == second.get(field) for field in fields)


def _index_records_by_identity(records: Iterable[Mapping[str, Any]]) -> dict[tuple[Any, Any], Mapping[str, Any]]:
    index: dict[tuple[Any, Any], Mapping[str, Any]] = {}
    for record in records:
        key = (record["entity_kind"], record["ref"])
        if key in index:
            raise ValueError(f"duplicate entity record for entity_kind/ref {key!r}")
        index[key] = record
    return index


def entities_equal(first: Iterable[Mapping[str, Any]], second: Iterable[Mapping[str, Any]]) -> bool:
    """Compare two entities sections by content, ignoring list order.

    Each record is keyed by (entity_kind, ref) -- exactly the identity a
    canonical record carries -- so two sections with the same records in a
    different order compare equal, while a single differing property on any
    one record makes them compare unequal.
    """
    first_index = _index_records_by_identity(first)
    second_index = _index_records_by_identity(second)
    if set(first_index) != set(second_index):
        return False
    return all(records_equal(first_index[key], second_index[key]) for key in first_index)


def _relation_triple_set(relations: Iterable[Mapping[str, Any]]) -> set[tuple[Any, Any, Any]]:
    return {
        (relation["source_ref"], relation["target_ref"], relation["field_ref"])
        for relation in relations
    }


def relations_equal(first: Iterable[Mapping[str, Any]], second: Iterable[Mapping[str, Any]]) -> bool:
    """Compare two relations sections as unordered triple sets."""
    return _relation_triple_set(first) == _relation_triple_set(second)


def documents_equal(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """Semantic equality of two documents: same format_version, same entity
    content (order-independent), same relation triples (order-independent).

    This intentionally ignores "checksum": two documents can be semantically
    equal while carrying different checksums only if one was tampered with
    (checksum then disagrees with content) -- `verify_document` is the
    dedicated check for that, kept separate from this content comparison.
    """
    return (
        first.get("format_version") == second.get("format_version")
        and entities_equal(first.get("entities", ()), second.get("entities", ()))
        and relations_equal(first.get("relations", ()), second.get("relations", ()))
    )
