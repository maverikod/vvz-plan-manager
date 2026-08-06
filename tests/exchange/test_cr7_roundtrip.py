"""CR-7 G-005/T-002/A-001: canonical round-trip fidelity, closure evidence for
todo 09a4d9af.

Proves, with NO live PostgreSQL anywhere in this module:

(1) Round-trip fidelity: export the full registry from a populated store,
    import into an empty scratch store, export again -- the two export
    documents are byte-identical (checksum discipline) and semantically
    identical via canonical_form's own comparison helpers (entities by ref
    and every property; relations as an unordered triple set).
(2) Identity preservation: original refs and timestamps survive the import
    through the recovery/import admission path.
(3) Same-kind replacement: re-importing over an existing ref of the same
    kind clears and replaces the row, never duplicates it.
(4) Cross-kind conflict: a planted ref already registered under a DIFFERENT
    kind aborts the import, with no partial write of the conflicting row.
(5) The exporter's excluded-content list is asserted exact, so nothing is
    silently dropped from the walked registry without a named reason.

The "empty scratch database" this module needs is a real IN-MEMORY store
(genuine INSERT/SELECT/UPDATE/DELETE state), not a canned-row replay: the
round trip populates store A, exports it, imports into store B, and
re-exports B, so a second store must actually hold what was written to it.
tests/exchange/test_exporter_canonical.py and test_importer_canonical.py
fake single-shot canned responses (a script of predicate -> rows) because
their tests only ever issue reads (or one insert whose result is never read
back); that idiom does not extend to a real round trip, so this module
extends it into a small, deliberately narrow, dict-table-backed engine that
supports exactly the statement shapes the exporter/importer/relation_index_
store surfaces issue (see FakeCanonicalStore's own docstring) -- a test
fixture, not a general SQL engine.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.domain.provider import Provider
from plan_manager.domain.tool import Tool
from plan_manager.domain.toolset import Toolset, ToolsetMembership
from plan_manager.domain.wish import WishItem
from plan_manager.exchange import canonical_form as cf
from plan_manager.exchange import exporter, importer


# ---------------------------------------------------------------------------
# FakeCanonicalStore: a genuinely stateful fake psycopg connection.
# ---------------------------------------------------------------------------


class _Column:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]], columns: list[str]) -> None:
        self._rows = rows
        self._columns = columns

    @property
    def description(self):
        return [_Column(name) for name in self._columns]

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


_INSERT_RE = re.compile(
    r'^INSERT INTO "?(?P<table>[A-Za-z_][A-Za-z0-9_]*)"? '
    r"\((?P<cols>.*?)\) VALUES \((?P<vals>.*?)\)"
    r"(?: ON CONFLICT \((?P<conflict>[A-Za-z_]+)\) DO NOTHING)?$"
)
_UPDATE_RE = re.compile(
    r'^UPDATE "?(?P<table>[A-Za-z_][A-Za-z0-9_]*)"? SET (?P<set>.+) WHERE (?P<where>.+)$'
)
_DELETE_RE = re.compile(
    r'^DELETE FROM "?(?P<table>[A-Za-z_][A-Za-z0-9_]*)"?(?: WHERE (?P<where>.+))?$'
)
_WHERE_EQ_RE = re.compile(r'^"?([A-Za-z_][A-Za-z0-9_]*)"? = %s$')
_WHERE_ANY_RE = re.compile(r'^"?([A-Za-z_][A-Za-z0-9_]*)"? = ANY\(%s\)$')
_WHERE_NULL_RE = re.compile(r'^"?([A-Za-z_][A-Za-z0-9_]*)"? IS NULL$')
_SET_COL_RE = re.compile(r'"?([A-Za-z_][A-Za-z0-9_]*)"? = %s')


class FakeCanonicalStore:
    """A dict-table-backed fake psycopg connection: an "empty scratch database".

    Actually maintains state across statements (INSERT stores rows, SELECT
    serves them, UPDATE mutates them, DELETE removes them) -- unlike the
    single-shot canned-row fakes in test_exporter_canonical.py and
    test_importer_canonical.py, which never need a second read to reflect a
    first write. Only the small, closed set of statement shapes the
    exporter/importer/relation_index_store surfaces actually issue is
    supported (verified against plan_manager.domain.entity's crud_get/
    crud_list/crud_create/crud_update, plan_manager.storage.identity's
    register_entity_identity/resolve_entity_identity, and
    plan_manager.storage.relation_index_store's references_from/
    replace_index): a bare or single-equality-predicate SELECT, an INSERT
    with an optional ON CONFLICT (col) DO NOTHING, an UPDATE with a SET list
    and a WHERE predicate, and a whole-table DELETE. Every executed statement
    is recorded verbatim in ``executed`` for assertions that need it.
    """

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql_obj: Any, params: Any = ()) -> _FakeCursor:
        rendered = sql_obj.as_string(None) if hasattr(sql_obj, "as_string") else str(sql_obj)
        flat = " ".join(rendered.split())
        params = tuple(params)
        self.executed.append((flat, params))

        body, returning = flat, None
        if " RETURNING " in body:
            body, returning = body.split(" RETURNING ", 1)

        if body.startswith("SELECT "):
            return self._select(body, params)
        if body.startswith("INSERT INTO "):
            return self._insert(body, params, returning)
        if body.startswith("UPDATE "):
            return self._update(body, params, returning)
        if body.startswith("DELETE FROM "):
            return self._delete(body)
        raise AssertionError(f"FakeCanonicalStore: unsupported statement: {flat!r}")

    # -- SELECT --------------------------------------------------------

    def _select(self, body: str, params: tuple[Any, ...]) -> _FakeCursor:
        rest = body[len("SELECT "):]
        cols_part, rest = rest.split(" FROM ", 1)
        table_match = re.match(r'^"?([A-Za-z_][A-Za-z0-9_]*)"?', rest)
        assert table_match, rest
        table = table_match.group(1)
        rest = rest[table_match.end():].strip()
        where = rest[len("WHERE "):].strip() if rest.startswith("WHERE ") else None

        rows = self.tables.get(table, [])
        if where:
            rows = [row for row in rows if self._row_matches(row, where, params)]

        cols_raw = cols_part.strip()
        if cols_raw == "1":  # existence-check idiom (crud_create's recovery check)
            return _FakeCursor([(1,) for _ in rows], ["?column?"])
        if cols_raw == "*":
            columns = sorted({key for row in rows for key in row})
        else:
            columns = [c.strip().strip('"') for c in cols_raw.split(",")]
        out_rows = [tuple(row.get(col) for col in columns) for row in rows]
        return _FakeCursor(out_rows, columns)

    def _row_matches(self, row: dict[str, Any], where: str, params: tuple[Any, ...]) -> bool:
        clauses = where.split(" AND ")
        param_iter = iter(params)
        for clause in clauses:
            clause = clause.strip()
            any_match = _WHERE_ANY_RE.match(clause)
            if any_match:
                if row.get(any_match.group(1)) not in next(param_iter):
                    return False
                continue
            eq_match = _WHERE_EQ_RE.match(clause)
            if eq_match:
                if row.get(eq_match.group(1)) != next(param_iter):
                    return False
                continue
            null_match = _WHERE_NULL_RE.match(clause)
            if null_match:
                if row.get(null_match.group(1)) is not None:
                    return False
                continue
            raise AssertionError(f"FakeCanonicalStore: unsupported predicate clause: {clause!r}")
        return True

    # -- INSERT ----------------------------------------------------------

    def _insert(self, body: str, params: tuple[Any, ...], returning: str | None) -> _FakeCursor:
        match = _INSERT_RE.match(body)
        assert match, body
        table = match.group("table")
        columns = [c.strip().strip('"') for c in match.group("cols").split(",")]
        assert len(columns) == len(params), (columns, params)
        rows = self.tables.setdefault(table, [])
        conflict_col = match.group("conflict")
        if conflict_col:
            conflict_value = dict(zip(columns, params)).get(conflict_col)
            if any(row.get(conflict_col) == conflict_value for row in rows):
                return _FakeCursor([], [])  # ON CONFLICT ... DO NOTHING: a no-op
        new_row = dict(zip(columns, params))
        rows.append(new_row)
        if not returning:
            return _FakeCursor([], [])
        ret_cols = [c.strip().strip('"') for c in returning.split(",")]
        return _FakeCursor([tuple(new_row.get(c) for c in ret_cols)], ret_cols)

    # -- UPDATE ------------------------------------------------------------

    def _update(self, body: str, params: tuple[Any, ...], returning: str | None) -> _FakeCursor:
        match = _UPDATE_RE.match(body)
        assert match, body
        table = match.group("table")
        set_cols = _SET_COL_RE.findall(match.group("set"))
        where = match.group("where")
        set_params = params[: len(set_cols)]
        where_params = params[len(set_cols):]
        updated: list[dict[str, Any]] = []
        for row in self.tables.get(table, []):
            if self._row_matches(row, where, where_params):
                row.update(dict(zip(set_cols, set_params)))
                updated.append(row)
        if not returning:
            return _FakeCursor([], [])
        ret_cols = [c.strip().strip('"') for c in returning.split(",")]
        return _FakeCursor([tuple(row.get(c) for c in ret_cols) for row in updated], ret_cols)

    # -- DELETE --------------------------------------------------------------

    def _delete(self, body: str) -> _FakeCursor:
        match = _DELETE_RE.match(body)
        assert match, body
        table = match.group("table")
        where = match.group("where")
        if where is None:
            self.tables[table] = []  # replace_index's whole-table clear
        else:  # not exercised by this module's scenarios; kept for completeness
            rows = self.tables.get(table, [])
            self.tables[table] = [row for row in rows if not self._row_matches(row, where, ())]
        return _FakeCursor([], [])


def _seed(store: FakeCanonicalStore, entity_cls: type, row: dict[str, Any]) -> None:
    """Seed one entity row plus its identity-registry entry into a store.

    Mirrors production state: every live entity row has a matching
    entity_identity row (register_entity_identity's own transaction
    invariant), which the importer's identity-state check depends on.
    """
    store.tables.setdefault(entity_cls.TABLE_NAME, []).append(row)
    ref_column = cf._entity_ref_column(entity_cls)
    store.tables.setdefault("entity_identity", []).append(
        {
            "id": row[ref_column],
            "table_name": entity_cls.TABLE_NAME,
            "entity_type": entity_cls.ENTITY_TYPE,
            "created_at": row.get(entity_cls.CREATED_AT_COLUMN),
        }
    )


# ---------------------------------------------------------------------------
# Representative multi-kind fixture: six real, uuid-keyed entity kinds
# (catalog roots, an owned membership row, and two anchor-carrying runtime
# kinds), one of them soft-deleted (markdel), each with its own distinct
# created_at/updated_at so identity preservation is checked per record. Two
# relation_index triples are planted (toolset_membership -> tool,
# calendar_entry -> wish) so the relations section is exercised too.
# ---------------------------------------------------------------------------


def _dummy_value(column: str, salt: str) -> Any:
    if column.endswith("uuid") or column.endswith("_id"):
        return uuid.uuid4()
    return f"{salt}::{column}"


def _build_row(
    entity_cls: type,
    *,
    salt: str,
    created_at: datetime,
    updated_at: datetime,
    marked: bool = False,
) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for column in entity_cls.COLUMNS:
        if column == entity_cls.CREATED_AT_COLUMN:
            row[column] = created_at
        elif column == entity_cls.UPDATED_AT_COLUMN:
            row[column] = updated_at
        elif column == entity_cls.SOFT_DELETE_COLUMN:
            row[column] = datetime(2026, 1, 9, tzinfo=timezone.utc) if marked else None
        else:
            row[column] = _dummy_value(column, salt)
    return row


def _build_populated_store_a() -> tuple[FakeCanonicalStore, dict[str, dict[str, Any]]]:
    """A store with six representative, distinctly-timestamped rows and two
    relation_index triples, keyed by entity_kind for the tests to inspect."""
    store = FakeCanonicalStore()
    rows_by_kind: dict[str, dict[str, Any]] = {}

    def make(entity_cls: type, *, year: int, marked: bool = False) -> dict[str, Any]:
        row = _build_row(
            entity_cls,
            salt=entity_cls.ENTITY_TYPE,
            created_at=datetime(year, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(year, 6, 15, tzinfo=timezone.utc),
            marked=marked,
        )
        row["uuid"] = uuid.uuid4()
        _seed(store, entity_cls, row)
        rows_by_kind[entity_cls.ENTITY_TYPE] = row
        return row

    tool_row = make(Tool, year=2020)
    make(Provider, year=2021)
    wish_row = make(WishItem, year=2022)
    calendar_row = make(CalendarEntry, year=2023)
    make(Toolset, year=2024)
    membership_row = make(ToolsetMembership, year=2025, marked=True)  # the marked row

    store.tables.setdefault("relation_index", []).extend(
        [
            {
                "source_ref": membership_row["uuid"],
                "target_ref": tool_row["uuid"],
                "field_ref": uuid.uuid4(),
            },
            {
                "source_ref": calendar_row["uuid"],
                "target_ref": wish_row["uuid"],
                "field_ref": uuid.uuid4(),
            },
        ]
    )
    return store, rows_by_kind


REPRESENTATIVE_KINDS = frozenset(
    {"tool", "provider", "wish", "calendar_entry", "toolset", "toolset_membership"}
)


def _representative_document(store: FakeCanonicalStore) -> dict[str, Any]:
    """Export ``store`` through the real exporter, scoped to this module's kinds.

    canonical_form.registered_entity_classes() walks the process-global
    DataclassEntity subclass registry (by its own docstring's design), so
    once another test module has been imported into the same pytest session
    its own DataclassEntity fixtures become visible to that walk too. Some
    fixtures deliberately reuse a REAL TABLE_NAME for a narrowly-scoped
    probe of their own (e.g. tests/domain/test_entity.py's _SDRelated,
    TABLE_NAME="wish_item") -- harmless there, because that module's own
    fake connections never share table content with this one. This
    module's FakeCanonicalStore, however, keys rows by table name alone
    (exactly like a real database), so a full-suite run can make such a
    probe's SELECT answer with this module's own seeded row, surfacing a
    same-ref record under a foreign entity_kind that never exists in real
    production (every real entity kind owns its own table; this collision
    is a cross-test-module fixture artifact only). Scoping the round trip
    to REPRESENTATIVE_KINDS keeps the checked document exactly what this
    module populated, the same accommodation
    test_exporter_canonical.py's own registered_classes_tests_origin_
    filtered already makes for the identical hazard.
    """
    document = exporter.export_canonical_document(store)["document"]
    entities = [
        record for record in document["entities"] if record["entity_kind"] in REPRESENTATIVE_KINDS
    ]
    body = {
        "format_version": document["format_version"],
        "entities": entities,
        "relations": document["relations"],
    }
    checksum = cf.compute_checksum(cf._canonical_json_bytes(body))
    return {**body, "checksum": checksum}


# ---------------------------------------------------------------------------
# (1) Round-trip fidelity: export -> import into empty store -> export again.
# Byte-identical (checksum discipline) and semantically identical.
# ---------------------------------------------------------------------------


def test_round_trip_is_byte_identical_and_semantically_identical() -> None:
    store_a, _ = _build_populated_store_a()
    doc1 = _representative_document(store_a)
    assert cf.verify_document(doc1) is True

    store_b = FakeCanonicalStore()  # the empty scratch database
    result = importer.import_canonical_document(store_b, doc1)
    assert result["entities_created"] == 6
    assert result["entities_replaced"] == 0
    assert result["relations_written"] == 2

    doc2 = _representative_document(store_b)
    assert cf.verify_document(doc2) is True

    # Checksum discipline: exact byte equality of the two export documents.
    assert cf.serialize_document(doc1) == cf.serialize_document(doc2)
    # Semantic equality via canonical_form's own comparison helpers.
    assert cf.documents_equal(doc1, doc2) is True
    assert cf.entities_equal(doc1["entities"], doc2["entities"]) is True
    assert cf.relations_equal(doc1["relations"], doc2["relations"]) is True


def test_round_trip_covers_every_representative_kind() -> None:
    store_a, rows_by_kind = _build_populated_store_a()
    doc1 = exporter.export_canonical_document(store_a)["document"]
    kinds = {record["entity_kind"] for record in doc1["entities"]}
    assert REPRESENTATIVE_KINDS <= kinds
    assert set(rows_by_kind) == REPRESENTATIVE_KINDS


# ---------------------------------------------------------------------------
# (2) Identity preservation: original refs and timestamps survive the import
# through the recovery/import admission path.
# ---------------------------------------------------------------------------


def test_identity_and_timestamps_survive_the_recovery_path() -> None:
    store_a, rows_by_kind = _build_populated_store_a()
    doc1 = _representative_document(store_a)
    store_b = FakeCanonicalStore()
    importer.import_canonical_document(store_b, doc1)
    doc2 = _representative_document(store_b)

    by_kind_2 = {record["entity_kind"]: record for record in doc2["entities"]}
    for kind, original_row in rows_by_kind.items():
        record = by_kind_2[kind]
        assert record["ref"] == str(original_row["uuid"])
        assert record["created_at"] == original_row["created_at"].isoformat()
        assert record["updated_at"] == original_row["updated_at"].isoformat()

    # The marked row's markdel state also survived (boolean, per canonical_form).
    assert by_kind_2["toolset_membership"]["markdel"] is True
    assert by_kind_2["tool"]["markdel"] is False

    # Recovery-created rows in the target store actually carry the original ref.
    recovered_tool_refs = {row["uuid"] for row in store_b.tables["tool"]}
    assert recovered_tool_refs == {rows_by_kind["tool"]["uuid"]}


# ---------------------------------------------------------------------------
# (3) Same-kind replacement: re-import over an existing ref of the same kind
# clears and replaces, never duplicates.
# ---------------------------------------------------------------------------


def test_same_kind_reimport_clears_and_replaces_not_duplicates() -> None:
    store = FakeCanonicalStore()
    ref = uuid.uuid4()
    original_row = _build_row(
        Tool,
        salt="original",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2020, 1, 2, tzinfo=timezone.utc),
    )
    original_row["uuid"] = ref
    _seed(store, Tool, original_row)

    updated_row = dict(original_row)
    updated_row["name"] = "renewed-tool-name"
    updated_row["updated_at"] = datetime(2026, 3, 4, tzinfo=timezone.utc)
    document = cf.build_document([(Tool, updated_row)], [])

    result = importer.import_canonical_document(store, document)

    assert result == {"entities_created": 0, "entities_replaced": 1, "relations_written": 0}
    tool_rows = store.tables["tool"]
    assert len(tool_rows) == 1  # cleared and replaced, never duplicated
    assert tool_rows[0]["uuid"] == ref  # the ref itself never moves
    assert tool_rows[0]["name"] == "renewed-tool-name"
    assert tool_rows[0]["updated_at"] == datetime(2026, 3, 4, tzinfo=timezone.utc)
    # entity_identity gained no second row for the same ref.
    identity_rows = [row for row in store.tables["entity_identity"] if row["id"] == ref]
    assert len(identity_rows) == 1


# ---------------------------------------------------------------------------
# (4) Cross-kind conflict: a planted mismatched-kind ref aborts the import,
# with no partial write of the conflicting row.
# ---------------------------------------------------------------------------


def test_cross_kind_conflict_aborts_with_no_partial_write() -> None:
    store = FakeCanonicalStore()
    ref = uuid.uuid4()
    # The ref is already registered, but under a DIFFERENT kind (provider).
    store.tables["entity_identity"] = [
        {
            "id": ref,
            "table_name": "provider",
            "entity_type": "provider",
            "created_at": datetime(2020, 1, 1, tzinfo=timezone.utc),
        }
    ]

    tool_row = _build_row(
        Tool,
        salt="conflict",
        created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    tool_row["uuid"] = ref
    document = cf.build_document([(Tool, tool_row)], [])

    try:
        importer.import_canonical_document(store, document)
        raise AssertionError("expected a cross-kind identity conflict to abort the import")
    except ValueError as exc:
        assert "identity conflict" in str(exc)

    # No partial write: the "tool" table stays empty and the registry keeps
    # exactly the one, unaltered, original (provider-kind) entry.
    assert store.tables.get("tool", []) == []
    assert len(store.tables["entity_identity"]) == 1
    assert store.tables["entity_identity"][0]["entity_type"] == "provider"


# ---------------------------------------------------------------------------
# (5) The excluded-content list is exact -- nothing silently dropped.
# ---------------------------------------------------------------------------


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


def test_excluded_content_list_is_exact() -> None:
    store_a, _ = _build_populated_store_a()
    result = exporter.export_canonical_document(store_a)
    excluded = result["excluded_content"]

    assert excluded == [dict(entry) for entry in exporter.EXCLUDED_CONTENT]
    excluded_kinds = {entry["kind"] for entry in excluded}
    assert excluded_kinds == EXPECTED_EXCLUDED_KINDS
    for entry in excluded:
        assert set(entry) == {"kind", "reason"}
        assert isinstance(entry["reason"], str) and entry["reason"].strip()
    # None of the representative kinds this module round-trips is excluded.
    assert excluded_kinds.isdisjoint(REPRESENTATIVE_KINDS)


# ---------------------------------------------------------------------------
# RED path: each planted defect variant must be DETECTED by canonical_form's
# comparison helpers, proving the equality checks used above are not
# vacuously true. Every variant starts from a genuine exported document.
# ---------------------------------------------------------------------------


def _exported_document() -> dict[str, Any]:
    store_a, _ = _build_populated_store_a()
    return exporter.export_canonical_document(store_a)["document"]


def test_mutated_property_is_detected() -> None:
    doc1 = _exported_document()
    doc2 = copy.deepcopy(doc1)
    record = doc2["entities"][0]
    record["properties"] = dict(record["properties"])
    a_property = next(iter(record["properties"]))
    record["properties"][a_property] = "TAMPERED-VALUE-8f2c"

    assert cf.serialize_document(doc1) != cf.serialize_document(doc2)
    assert cf.documents_equal(doc1, doc2) is False
    assert cf.entities_equal(doc1["entities"], doc2["entities"]) is False


def test_dropped_relation_triple_is_detected() -> None:
    doc1 = _exported_document()
    assert doc1["relations"], "fixture must plant at least one relation triple"
    doc2 = copy.deepcopy(doc1)
    doc2["relations"].pop()

    assert cf.serialize_document(doc1) != cf.serialize_document(doc2)
    assert cf.documents_equal(doc1, doc2) is False
    assert cf.relations_equal(doc1["relations"], doc2["relations"]) is False


def test_changed_ref_is_detected() -> None:
    doc1 = _exported_document()
    doc2 = copy.deepcopy(doc1)
    doc2["entities"][0] = dict(doc2["entities"][0])
    doc2["entities"][0]["ref"] = str(uuid.uuid4())

    assert cf.serialize_document(doc1) != cf.serialize_document(doc2)
    assert cf.documents_equal(doc1, doc2) is False
    assert cf.entities_equal(doc1["entities"], doc2["entities"]) is False


def test_changed_timestamp_is_detected() -> None:
    doc1 = _exported_document()
    doc2 = copy.deepcopy(doc1)
    doc2["entities"][0] = dict(doc2["entities"][0])
    doc2["entities"][0]["updated_at"] = "1999-01-01T00:00:00+00:00"

    assert cf.serialize_document(doc1) != cf.serialize_document(doc2)
    assert cf.documents_equal(doc1, doc2) is False
    assert cf.entities_equal(doc1["entities"], doc2["entities"]) is False
