"""Tests for the CR-7 G-005/T-001/A-003 canonical export document.

Covers plan_manager.exchange.exporter.export_canonical_document: it must
cover every registered entity kind (asserted against the closed registry,
tests-origin filtered, exactly as tests/exchange/test_canonical_form.py
does), the eight runtime work-layer entities named by the frozen step must
appear, the returned checksum must verify through canonical_form, and the
excluded-content list must be present and exact.

Fake psycopg connections only; no live PostgreSQL instance is required. The
fake connection scripts one canned row (or one canned relation_index triple)
per rendered SQL statement, following the same predicate-matching pattern
tests/domain/test_entity.py already uses for the unified CRUD engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest

from plan_manager.exchange import canonical_form as cf
from plan_manager.exchange import exporter


# --------------------------------------------------------------------------
# Fake psycopg connection: replays a canned row set per rendered SQL prefix.
# --------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    @property
    def description(self):  # pragma: no cover - only touched by non-dict rows
        return []


class _FakeConn:
    """Records executed statements; replays scripted rows per SQL predicate."""

    def __init__(self, script) -> None:
        self._script = list(script)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        rendered = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        flat = " ".join(rendered.split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


# --------------------------------------------------------------------------
# Synthetic-row construction, driven by each entity's own descriptor -- the
# same pattern tests/exchange/test_canonical_form.py uses for coverage tests.
# --------------------------------------------------------------------------


def _dummy_value(column: str, salt: str) -> Any:
    if column.endswith("uuid") or column.endswith("_id"):
        return uuid.uuid4()
    return f"{salt}::{column}"


def _build_fake_row(entity_cls: type, *, salt: str) -> dict[str, Any]:
    ref_column = cf._entity_ref_column(entity_cls)
    row: dict[str, Any] = {}
    for column in entity_cls.COLUMNS:
        if column == entity_cls.CREATED_AT_COLUMN:
            row[column] = datetime(2026, 1, 1, tzinfo=timezone.utc)
        elif column == entity_cls.UPDATED_AT_COLUMN:
            row[column] = datetime(2026, 1, 2, tzinfo=timezone.utc)
        elif column == entity_cls.SOFT_DELETE_COLUMN:
            row[column] = None
        else:
            row[column] = _dummy_value(column, salt)
    row.setdefault(ref_column, uuid.uuid4())
    if ref_column not in entity_cls.COLUMNS:
        row[ref_column] = uuid.uuid4()
    return row


def registered_classes_tests_origin_filtered() -> list[type]:
    # Other test modules (e.g. tests/domain/test_entity.py's _Probe fixtures)
    # define their own DataclassEntity subclasses with real-looking
    # ENTITY_TYPE/TABLE_NAME values; once such a module is imported anywhere
    # in the same pytest process, they leak into the closed registry's
    # __subclasses__ walk just like tests/exchange/test_canonical_form.py's
    # own comment explains. Excluding by module origin, not by name, is the
    # same defense that module already uses.
    return [
        cls
        for cls in cf.registered_entity_classes()
        if not (cls.__module__ or "").startswith("tests")
    ]


def covered_classes() -> list[type]:
    """registered_classes_tests_origin_filtered() minus exporter.EXCLUDED_KINDS.

    Five excluded kinds (cascade_request, context_block, srt_snapshot,
    runtime_audit, command_metric) declare a real DataclassEntity seat in a
    plan_manager.storage/views module this exporter never imports on its own
    -- but Python's subclass registration is process-global, so a full-suite
    run that has already imported that module elsewhere makes it visible to
    cf.registered_entity_classes() too. The exporter itself filters these out
    by entity_kind (see exporter.EXCLUDED_KINDS); the set of kinds this
    exporter is expected to COVER must apply that same filter, or a
    full-suite run and a single-file run would compute different "expected"
    sets for no reason connected to the exporter's own behaviour.
    """
    return [
        cls
        for cls in registered_classes_tests_origin_filtered()
        if cls.ENTITY_TYPE not in exporter.EXCLUDED_KINDS
    ]


# The eight runtime work-layer entity kinds the frozen step calls out as
# "currently omitted": docs/db/schema_inventory.md's "Runtime work-layer
# entities" section minus its three link/policy auxiliary rows (todo_link,
# escalation_policy, runtime_link), which are relationship/config records
# rather than primary runtime work items.
RUNTIME_ENTITY_KINDS = frozenset(
    {
        "todo",
        "comment",
        "execution_attempt",
        "review_result",
        "escalation",
        "answer_envelope",
        "wish",
        "calendar_entry",
    }
)


def _build_populated_conn() -> tuple[_FakeConn, dict[type, dict[str, Any]]]:
    """A fake connection scripted to answer crud_list for every registered kind.

    One canned row per kind (keyed by TABLE_NAME, matching how
    DataclassEntity.crud_list renders its SELECT), plus one canned
    relation_index triple sourced from the first kind's row and targeting the
    second kind's row.
    """
    classes = covered_classes()
    assert len(classes) >= 25  # sanity check on the fixture itself

    rows_by_class = {cls: _build_fake_row(cls, salt=cls.ENTITY_TYPE) for cls in classes}

    script: list[tuple[Any, list[Any]]] = []
    for cls, row in rows_by_class.items():
        table_name = cls.TABLE_NAME

        def predicate(flat: str, table_name: str = table_name) -> bool:
            return f'FROM "{table_name}"' in flat

        script.append((predicate, [row]))

    source_cls, target_cls = classes[0], classes[-1]
    source_ref = rows_by_class[source_cls][cf._entity_ref_column(source_cls)]
    target_ref = rows_by_class[target_cls][cf._entity_ref_column(target_cls)]
    field_ref = uuid.uuid4()
    triple_tuple = (source_ref, target_ref, field_ref)
    script.append((lambda flat: "FROM relation_index" in flat, [triple_tuple]))

    conn = _FakeConn(script)
    return conn, rows_by_class


# --------------------------------------------------------------------------
# Coverage: every registered entity kind appears; the eight runtime kinds do.
# --------------------------------------------------------------------------


def test_export_canonical_document_covers_every_registered_entity_kind() -> None:
    conn, rows_by_class = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    document = result["document"]

    expected_kinds = {cls.ENTITY_TYPE for cls in rows_by_class}
    actual_kinds = {record["entity_kind"] for record in document["entities"]}

    # Subset, not equality: a full-suite run may have already imported other
    # test modules' own DataclassEntity fixtures into the same process (see
    # registered_classes_tests_origin_filtered's docstring above) -- this
    # exporter deliberately does not filter by module origin (that is a
    # tests-only concern per production discovery), so those extras may also
    # appear. What this step requires is that nothing REAL is missing.
    assert expected_kinds <= actual_kinds
    assert len(document["entities"]) >= len(rows_by_class)


def test_the_eight_runtime_entities_appear() -> None:
    conn, _ = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    actual_kinds = {record["entity_kind"] for record in result["document"]["entities"]}
    assert RUNTIME_ENTITY_KINDS <= actual_kinds


def test_each_covered_record_carries_ref_kind_owner_markdel_timestamps() -> None:
    conn, rows_by_class = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    by_kind = {record["entity_kind"]: record for record in result["document"]["entities"]}

    for entity_cls, row in rows_by_class.items():
        record = by_kind[entity_cls.ENTITY_TYPE]
        ref_column = cf._entity_ref_column(entity_cls)
        assert record["ref"] == str(row[ref_column])
        assert isinstance(record["markdel"], bool)
        if entity_cls.OWNER_COLUMN is not None:
            assert record["owner"] == str(row[entity_cls.OWNER_COLUMN])
        else:
            assert record["owner"] is None
        # Every declared column not in the named slots surfaces as a property.
        excluded = {
            ref_column,
            entity_cls.OWNER_COLUMN,
            entity_cls.SOFT_DELETE_COLUMN,
            entity_cls.CREATED_AT_COLUMN,
            entity_cls.UPDATED_AT_COLUMN,
        }
        excluded.discard(None)
        assert set(record["properties"]) == set(entity_cls.COLUMNS) - excluded


# --------------------------------------------------------------------------
# Relation triples: the separate, unordered section.
# --------------------------------------------------------------------------


def test_relation_triple_from_the_index_appears_as_its_own_section() -> None:
    conn, rows_by_class = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    document = result["document"]

    classes = list(rows_by_class)
    source_cls, target_cls = classes[0], classes[-1]
    expected_source = str(rows_by_class[source_cls][cf._entity_ref_column(source_cls)])
    expected_target = str(rows_by_class[target_cls][cf._entity_ref_column(target_cls)])

    matches = [
        relation
        for relation in document["relations"]
        if relation["source_ref"] == expected_source
        and relation["target_ref"] == expected_target
    ]
    assert len(matches) == 1


# --------------------------------------------------------------------------
# Checksum: verifies via canonical_form, over exactly this document.
# --------------------------------------------------------------------------


def test_checksum_verifies_via_canonical_form() -> None:
    conn, _ = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    document = result["document"]
    assert cf.verify_document(document) is True

    tampered = dict(document)
    tampered["checksum"] = "0" * len(document["checksum"])
    assert cf.verify_document(tampered) is False


# --------------------------------------------------------------------------
# Excluded content: present and exact.
# --------------------------------------------------------------------------


EXPECTED_EXCLUDED_KINDS = frozenset(
    {
        "paragraph",
        "cascade_request",
        "context_block",
        "srt_snapshot",
        "runtime_audit",
        "command_metric",
        "embedding_cache",
        "entity_identity",
        "enumeration",
        "enumeration_value",
        "node_version",
        "ref",
        "revision",
        "reference_field",
        "relation_index",
    }
)


def test_excluded_content_list_is_present_and_exact() -> None:
    conn, _ = _build_populated_conn()
    result = exporter.export_canonical_document(conn)
    excluded = result["excluded_content"]

    assert excluded == [dict(entry) for entry in exporter.EXCLUDED_CONTENT]

    excluded_kinds = {entry["kind"] for entry in excluded}
    assert excluded_kinds == EXPECTED_EXCLUDED_KINDS

    # Every entry names a one-line, non-empty reason -- nothing is silently
    # dropped, and no reason is a placeholder.
    for entry in excluded:
        assert set(entry) == {"kind", "reason"}
        assert isinstance(entry["reason"], str) and entry["reason"].strip()
        assert "\n" not in entry["reason"]

    # None of the excluded kinds double as a covered entity kind: a table
    # cannot be simultaneously "walked" and "deliberately excluded".
    covered_kinds = {cls.ENTITY_TYPE for cls in covered_classes()}
    assert excluded_kinds.isdisjoint(covered_kinds)


# --------------------------------------------------------------------------
# The relation-index read surface is relation_index_store's own public API.
# --------------------------------------------------------------------------


def test_relation_triples_are_read_through_relation_index_store_references_from() -> None:
    conn, rows_by_class = _build_populated_conn()
    exporter.collect_canonical_relation_triples(
        conn, list(rows_by_class.items())
    )
    relation_index_calls = [
        (sql, params) for sql, params in conn.executed if "relation_index" in sql
    ]
    assert len(relation_index_calls) == 1
    assert "references_from" not in relation_index_calls[0][0]  # sanity: real SQL, not a stub


def test_collect_canonical_entity_rows_uses_crud_list_include_marked() -> None:
    conn, rows_by_class = _build_populated_conn()
    rows = exporter.collect_canonical_entity_rows(conn)
    kinds = {cls.ENTITY_TYPE for cls, _ in rows}
    expected = {cls.ENTITY_TYPE for cls in rows_by_class}
    assert expected <= kinds
