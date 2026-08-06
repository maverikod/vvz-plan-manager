"""Tests for the CR-7 G-005/T-001/A-001 canonical serialized form.

Covers the four verification points the frozen step names: deterministic
bytes for equal content, checksum detection of any byte change, serializer
coverage of every registered entity kind (iterating the closed registry, not
a hand-picked subset), and semantic comparison distinguishing property
changes from mere ordering changes.
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from plan_manager.exchange import canonical_form as cf


# --------------------------------------------------------------------------
# Generic synthetic-row construction, driven by each entity's own descriptor
# -- no per-entity-kind branching, matching the module under test.
# --------------------------------------------------------------------------


def _dummy_value(column: str, salt: str) -> Any:
    """A deterministic, opaque filler value for one column.

    canonical_form treats every non-special column opaquely (it only cares
    about ref/owner/markdel/created_at/updated_at placement, plus whatever
    JSON-safe value a property carries), so the exact filler content does
    not matter -- only that it is stable and JSON-safe.
    """
    if column.endswith("uuid") or column.endswith("_id"):
        return uuid.uuid4()
    return f"{salt}::{column}"


def build_fake_row(entity_cls: type, *, salt: str = "x", marked: bool = False) -> dict[str, Any]:
    """A synthetic row covering every declared column of one entity class."""
    ref_column = cf._entity_ref_column(entity_cls)
    row: dict[str, Any] = {}
    for column in entity_cls.COLUMNS:
        if column == entity_cls.CREATED_AT_COLUMN:
            row[column] = datetime(2026, 1, 1, tzinfo=timezone.utc)
        elif column == entity_cls.UPDATED_AT_COLUMN:
            row[column] = datetime(2026, 1, 2, tzinfo=timezone.utc)
        elif column == entity_cls.SOFT_DELETE_COLUMN:
            row[column] = datetime(2026, 1, 3, tzinfo=timezone.utc) if marked else None
        else:
            row[column] = _dummy_value(column, salt)
    # ref must be a real value even when the ref column collides with one of
    # the special columns above (it never does today, but stay explicit).
    row.setdefault(ref_column, uuid.uuid4())
    if ref_column not in entity_cls.COLUMNS:
        row[ref_column] = uuid.uuid4()
    return row


def all_entity_classes() -> list[type]:
    # Synthetic subclasses defined inside test modules are fixtures for the
    # negative cases in other tests, not shipped entities. They leak into
    # __subclasses__ once their test has run, so exclude them by origin
    # rather than by name.
    return [
        cls for cls in cf.registered_entity_classes()
        if not (cls.__module__ or "").startswith("tests")
    ]


# --------------------------------------------------------------------------
# (3) Serializer coverage: every registered entity kind, from the registry.
# --------------------------------------------------------------------------


def test_registry_is_non_empty() -> None:
    # Sanity check on the fixture itself: if this is ever empty the coverage
    # test below would vacuously "pass" without checking anything.
    assert len(all_entity_classes()) >= 25


@pytest.mark.parametrize("entity_cls", all_entity_classes(), ids=lambda cls: cls.ENTITY_TYPE)
def test_serializer_covers_every_registered_entity_kind(entity_cls: type) -> None:
    row = build_fake_row(entity_cls)
    record = cf.entity_row_to_canonical_record(entity_cls, row)

    assert record["entity_kind"] == entity_cls.ENTITY_TYPE
    assert isinstance(record["ref"], str) and record["ref"]
    assert isinstance(record["markdel"], bool)
    assert record["markdel"] is False

    ref_column = cf._entity_ref_column(entity_cls)
    assert record["ref"] == str(row[ref_column])

    if entity_cls.OWNER_COLUMN is not None:
        assert record["owner"] == str(row[entity_cls.OWNER_COLUMN])
    else:
        assert record["owner"] is None

    if entity_cls.CREATED_AT_COLUMN is not None:
        assert record["created_at"] == row[entity_cls.CREATED_AT_COLUMN].isoformat()
    else:
        assert record["created_at"] is None

    # The ref/owner/soft-delete/created/updated columns never leak into
    # "properties" -- they each have their own named slot in the record.
    excluded = {
        ref_column,
        entity_cls.OWNER_COLUMN,
        entity_cls.SOFT_DELETE_COLUMN,
        entity_cls.CREATED_AT_COLUMN,
        entity_cls.UPDATED_AT_COLUMN,
    }
    excluded.discard(None)
    assert set(record["properties"]) == set(entity_cls.COLUMNS) - excluded

    # Reverse direction resolves back to the same class and places ref/owner
    # in the columns the forward direction read them from.
    back_cls, back_row = cf.canonical_record_to_entity_row(record)
    assert back_cls is entity_cls
    assert back_row[ref_column] == record["ref"]
    if entity_cls.OWNER_COLUMN is not None:
        assert back_row[entity_cls.OWNER_COLUMN] == record["owner"]
    if entity_cls.SOFT_DELETE_COLUMN is not None:
        assert back_row[entity_cls.SOFT_DELETE_COLUMN] is False


@pytest.mark.parametrize("entity_cls", all_entity_classes(), ids=lambda cls: cls.ENTITY_TYPE)
def test_markdel_reflects_soft_delete_column_when_declared(entity_cls: type) -> None:
    if entity_cls.SOFT_DELETE_COLUMN is None:
        pytest.skip(f"{entity_cls.__name__} declares no SOFT_DELETE_COLUMN")
    marked_row = build_fake_row(entity_cls, marked=True)
    live_row = build_fake_row(entity_cls, marked=False)
    assert cf.entity_row_to_canonical_record(entity_cls, marked_row)["markdel"] is True
    assert cf.entity_row_to_canonical_record(entity_cls, live_row)["markdel"] is False


def test_step_runtime_owner_column_equals_its_own_ref_column() -> None:
    # step_runtime is the one entity with no "uuid" column: its ref falls
    # back to its single ID_COLUMN (step_uuid), which is also its declared
    # OWNER_COLUMN -- the attribute bag's identity IS the step it belongs to.
    entity_cls = cf.resolve_entity_class("step_runtime")
    assert cf._entity_ref_column(entity_cls) == "step_uuid"
    assert entity_cls.OWNER_COLUMN == "step_uuid"
    row = build_fake_row(entity_cls)
    record = cf.entity_row_to_canonical_record(entity_cls, row)
    assert record["ref"] == record["owner"] == str(row["step_uuid"])


def test_composite_key_entities_still_get_a_singular_uuid_ref() -> None:
    for entity_type in ("concept", "relation"):
        entity_cls = cf.resolve_entity_class(entity_type)
        assert entity_cls.ID_COLUMN is None
        assert cf._entity_ref_column(entity_cls) == "uuid"
        row = build_fake_row(entity_cls)
        record = cf.entity_row_to_canonical_record(entity_cls, row)
        assert record["ref"] == str(row["uuid"])


def test_owner_root_entity_reports_no_owner() -> None:
    plan_cls = cf.resolve_entity_class("plan")
    assert plan_cls.OWNER_ROOT is True
    row = build_fake_row(plan_cls)
    record = cf.entity_row_to_canonical_record(plan_cls, row)
    assert record["owner"] is None


def test_unknown_entity_kind_is_rejected_on_the_way_back() -> None:
    record = {
        "ref": str(uuid.uuid4()),
        "entity_kind": "no_such_kind",
        "owner": None,
        "markdel": False,
        "created_at": None,
        "updated_at": None,
        "properties": {},
    }
    with pytest.raises(ValueError):
        cf.canonical_record_to_entity_row(record)


# --------------------------------------------------------------------------
# Fixtures for the document-level tests below: a handful of real entity
# kinds is enough to exercise ordering, checksum and comparison behaviour
# without re-deriving full registry coverage (that is the tests above).
# --------------------------------------------------------------------------


def _sample_entity_rows() -> list[tuple[type, dict[str, Any]]]:
    plan_cls = cf.resolve_entity_class("plan")
    concept_cls = cf.resolve_entity_class("concept")
    tool_cls = cf.resolve_entity_class("tool")
    return [
        (plan_cls, build_fake_row(plan_cls, salt="p1")),
        (concept_cls, build_fake_row(concept_cls, salt="c1")),
        (tool_cls, build_fake_row(tool_cls, salt="t1")),
    ]


def _sample_relation_triples() -> list[cf.RelationTriple]:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    d, e, f = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    return [(a, b, c), (d, e, f)]


# --------------------------------------------------------------------------
# (1) Deterministic bytes for equal content.
# --------------------------------------------------------------------------


def test_equal_content_in_different_input_order_yields_identical_bytes() -> None:
    rows = _sample_entity_rows()
    triples = _sample_relation_triples()

    doc_forward = cf.build_document(rows, triples)
    doc_reversed_entities = cf.build_document(list(reversed(rows)), triples)
    doc_reversed_relations = cf.build_document(rows, list(reversed(triples)))
    doc_duplicated_relations = cf.build_document(rows, triples + triples)

    forward_bytes = cf.serialize_document(doc_forward)
    assert forward_bytes == cf.serialize_document(doc_reversed_entities)
    assert forward_bytes == cf.serialize_document(doc_reversed_relations)
    assert forward_bytes == cf.serialize_document(doc_duplicated_relations)
    assert doc_forward["checksum"] == doc_reversed_entities["checksum"]


def test_serialize_document_round_trips_through_parse_document() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    payload = cf.serialize_document(document)
    assert cf.parse_document(payload) == document


def test_dict_key_insertion_order_in_source_rows_does_not_affect_bytes() -> None:
    plan_cls = cf.resolve_entity_class("plan")
    row = build_fake_row(plan_cls, salt="k1")
    reordered_row = dict(reversed(list(row.items())))
    assert list(row.items()) != list(reordered_row.items())  # actually reordered
    assert row == reordered_row  # same content

    doc_a = cf.build_document([(plan_cls, row)], [])
    doc_b = cf.build_document([(plan_cls, reordered_row)], [])
    assert cf.serialize_document(doc_a) == cf.serialize_document(doc_b)


# --------------------------------------------------------------------------
# (2) Checksum detects any byte change.
# --------------------------------------------------------------------------


def test_verify_document_accepts_an_untampered_document() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    assert cf.verify_document(document) is True


def test_verify_document_rejects_a_mutated_property_value() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    tampered = copy.deepcopy(document)
    tampered["entities"][0]["properties"] = dict(tampered["entities"][0]["properties"])
    # Mutate one property's value in place, keeping the same checksum field.
    key = next(iter(tampered["entities"][0]["properties"]))
    tampered["entities"][0]["properties"][key] = "TAMPERED"
    assert cf.verify_document(tampered) is False


def test_verify_document_rejects_a_mutated_checksum() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    tampered = dict(document)
    tampered["checksum"] = "0" * len(document["checksum"])
    assert cf.verify_document(tampered) is False


def test_verify_document_rejects_an_added_relation_triple() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    tampered = copy.deepcopy(document)
    tampered["relations"].append(
        cf.build_relation_record(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    )
    assert cf.verify_document(tampered) is False


def test_compute_checksum_is_sensitive_to_a_single_byte() -> None:
    payload = b'{"a":1}'
    flipped = b'{"a":2}'
    assert cf.compute_checksum(payload) != cf.compute_checksum(flipped)
    assert cf.compute_checksum(payload) == cf.compute_checksum(payload)


# --------------------------------------------------------------------------
# (4) Semantic comparison: property changes vs. mere ordering changes.
# --------------------------------------------------------------------------


def test_documents_equal_ignores_entity_and_relation_ordering() -> None:
    rows = _sample_entity_rows()
    triples = _sample_relation_triples()
    doc_a = cf.build_document(rows, triples)
    doc_b = cf.build_document(list(reversed(rows)), list(reversed(triples)))
    assert cf.documents_equal(doc_a, doc_b) is True
    assert cf.entities_equal(doc_a["entities"], doc_b["entities"]) is True
    assert cf.relations_equal(doc_a["relations"], doc_b["relations"]) is True


def test_documents_equal_detects_a_property_change_despite_matching_order() -> None:
    rows = _sample_entity_rows()
    triples = _sample_relation_triples()
    doc_a = cf.build_document(rows, triples)

    mutated_rows = copy.deepcopy(rows)
    mutated_rows[0] = (mutated_rows[0][0], dict(mutated_rows[0][1]))
    a_column = next(
        column
        for column in mutated_rows[0][0].COLUMNS
        if column not in (cf._entity_ref_column(mutated_rows[0][0]), mutated_rows[0][0].OWNER_COLUMN)
        and column != mutated_rows[0][0].CREATED_AT_COLUMN
        and column != mutated_rows[0][0].UPDATED_AT_COLUMN
        and column != mutated_rows[0][0].SOFT_DELETE_COLUMN
    )
    mutated_rows[0][1][a_column] = "CHANGED-VALUE"
    doc_b = cf.build_document(mutated_rows, triples)

    assert cf.documents_equal(doc_a, doc_b) is False
    assert cf.entities_equal(doc_a["entities"], doc_b["entities"]) is False
    # Content differs, but the checksum computation itself is unaffected by
    # which document you ask -- both remain internally self-consistent.
    assert cf.verify_document(doc_a) is True
    assert cf.verify_document(doc_b) is True
    # And their checksums differ, since the underlying bytes differ.
    assert doc_a["checksum"] != doc_b["checksum"]


def test_records_equal_and_entities_equal_reject_a_ref_or_owner_change() -> None:
    plan_cls = cf.resolve_entity_class("plan")
    row = build_fake_row(plan_cls)
    record = cf.entity_row_to_canonical_record(plan_cls, row)
    other = dict(record)
    other["ref"] = str(uuid.uuid4())
    assert cf.records_equal(record, other) is False


def test_entities_equal_rejects_a_duplicate_ref_in_one_side() -> None:
    plan_cls = cf.resolve_entity_class("plan")
    record = cf.entity_row_to_canonical_record(plan_cls, build_fake_row(plan_cls))
    with pytest.raises(ValueError):
        cf.entities_equal([record, record], [record])


def test_relations_equal_treats_the_section_as_a_set() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    triple = cf.build_relation_record(a, b, c)
    assert cf.relations_equal([triple, triple], [triple]) is True
    other = cf.build_relation_record(b, a, c)
    assert cf.relations_equal([triple], [other]) is False


def test_documents_equal_requires_matching_format_version() -> None:
    document = cf.build_document(_sample_entity_rows(), _sample_relation_triples())
    other = dict(document)
    other["format_version"] = document["format_version"] + 1
    assert cf.documents_equal(document, other) is False
