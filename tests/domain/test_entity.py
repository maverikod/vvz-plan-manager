"""Regression suite for CR-7 G-001/T-001/A-002: the DataclassEntity admission boundary.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.domain.entity import DataclassEntity


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def description(self):  # pragma: no cover - only touched by returning paths
        return []


class _FakeConn:
    """Records executed statements; replays scripted rows per SQL prefix."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        rendered = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        flat = " ".join(rendered.split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


class _Probe(DataclassEntity):
    ENTITY_TYPE = "cr7_probe"
    TABLE_NAME = "calendar_entry"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "title", "created_at", "updated_at", "deleted_at")
    INSERT_COLUMNS = ("uuid", "title", "created_at", "updated_at")
    UPDATE_COLUMNS = ("title",)
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"
    REGISTER_IDENTITY = False


class _StrictProbe(_Probe):
    ENTITY_TYPE = "cr7_probe_strict"
    ENGINE_MANAGED_TIMESTAMPS = True


def test_create_validates_a_supplied_ref_as_uuid4() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="must be version 4"):
        _Probe.crud_create(
            conn, {"uuid": uuid.uuid1(), "title": "x"}, returning=False
        )
    assert conn.executed == []  # refused before any write

    good = uuid.uuid4()
    _Probe.crud_create(conn, {"uuid": str(good), "title": "x"}, returning=False)
    insert_sql, params = conn.executed[-1]
    assert insert_sql.startswith('INSERT INTO "calendar_entry"')
    assert params[0] == good  # string candidate normalized to the UUID value


def test_update_never_changes_ref() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="identity columns are immutable"):
        _Probe.crud_update(
            conn, uuid.uuid4(), {"uuid": uuid.uuid4()}, returning=False
        )
    assert conn.executed == []


def test_engine_managed_create_refuses_caller_timestamps_and_stamps_its_own() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="caller-supplied"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x", "created_at": datetime.now(timezone.utc)},
            returning=False,
        )
    assert conn.executed == []

    _StrictProbe.crud_create(
        conn, {"uuid": uuid.uuid4(), "title": "x"}, returning=False
    )
    insert_sql, params = conn.executed[-1]
    assert '"created_at"' in insert_sql and '"updated_at"' in insert_sql
    stamped = [value for value in params if isinstance(value, datetime)]
    assert len(stamped) == 2 and stamped[0] == stamped[1]


def test_engine_managed_update_refuses_caller_timestamps_and_refreshes_updated_at() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="refused on update"):
        _StrictProbe.crud_update(
            conn,
            uuid.uuid4(),
            {"title": "x", "updated_at": datetime.now(timezone.utc)},
            returning=False,
        )
    assert conn.executed == []

    _StrictProbe.crud_update(conn, uuid.uuid4(), {"title": "x"}, returning=False)
    update_sql, params = conn.executed[-1]
    assert '"updated_at" = %s' in update_sql
    assert any(isinstance(value, datetime) for value in params)


def test_legacy_entities_keep_store_stamped_timestamps() -> None:
    """ENGINE_MANAGED_TIMESTAMPS=False preserves the compatibility behaviour."""
    conn = _FakeConn()
    supplied = datetime.now(timezone.utc)
    _Probe.crud_create(
        conn,
        {"uuid": uuid.uuid4(), "title": "x", "created_at": supplied},
        returning=False,
    )
    _, params = conn.executed[-1]
    assert supplied in params


def test_admit_original_timestamps_requires_recovery_mode() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="requires recovery_mode"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x"},
            returning=False,
            admit_original_timestamps=True,
        )
    assert conn.executed == []


def test_recovery_mode_restores_a_missing_row_with_original_timestamps() -> None:
    original = datetime(2026, 1, 1, tzinfo=timezone.utc)
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT 1 FROM"), [])])
    _StrictProbe.crud_create(
        conn,
        {"uuid": uuid.uuid4(), "title": "x", "created_at": original},
        returning=False,
        recovery_mode=True,
        admit_original_timestamps=True,
    )
    absence_check, insert = conn.executed[0], conn.executed[-1]
    assert absence_check[0].startswith('SELECT 1 FROM "calendar_entry"')
    assert insert[0].startswith('INSERT INTO "calendar_entry"')
    assert original in insert[1]


def test_recovery_mode_never_replaces_an_existing_row() -> None:
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT 1 FROM"), [(1,)])])
    with pytest.raises(ValueError, match="never replaces an existing row"):
        _StrictProbe.crud_create(
            conn,
            {"uuid": uuid.uuid4(), "title": "x"},
            returning=False,
            recovery_mode=True,
        )
    assert not any(sql.startswith("INSERT") for sql, _ in conn.executed)


def test_recovery_mode_requires_the_original_identifier() -> None:
    conn = _FakeConn()
    with pytest.raises(ValueError, match="requires the original identifier"):
        _Probe.crud_create(
            conn, {"title": "x"}, returning=False, recovery_mode=True
        )


# --------------------------------------------------------------------------
# CR-7 G-003/T-001/A-001: ownership declaration surface.
# --------------------------------------------------------------------------


def test_ownership_states_are_mutually_exclusive() -> None:
    class _Bad(_Probe):
        ENTITY_TYPE = "cr7_probe_bad_owner"
        OWNER_COLUMN = "title"
        OWNER_ROOT = True

    with pytest.raises(ValueError, match="mutually exclusive"):
        _Bad.validate_ownership_declaration()


def test_owner_column_must_exist_in_columns() -> None:
    class _Bad(_Probe):
        ENTITY_TYPE = "cr7_probe_missing_owner_col"
        OWNER_COLUMN = "no_such_column"

    with pytest.raises(ValueError, match="absent from COLUMNS"):
        _Bad.validate_ownership_declaration()


def test_each_single_state_is_accepted() -> None:
    class _Col(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_col"
        OWNER_COLUMN = "title"

    class _Root(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_root"
        OWNER_ROOT = True

    class _Gap(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_gap"
        OWNER_GAP = "no usable owner column until the G-007 anchor collapse"

    for cls in (_Col, _Root, _Gap):
        cls.validate_ownership_declaration(require_ownership=True)


def test_completeness_is_enforced_only_on_request() -> None:
    class _Undeclared(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_undeclared"

    _Undeclared.validate_ownership_declaration()  # consistency only: passes
    with pytest.raises(ValueError, match="no ownership state declared"):
        _Undeclared.validate_ownership_declaration(require_ownership=True)


def test_gap_must_carry_a_statement() -> None:
    class _Blank(_Probe):
        ENTITY_TYPE = "cr7_probe_owner_blank_gap"
        OWNER_GAP = "   "

    with pytest.raises(ValueError, match="non-empty statement"):
        _Blank.validate_ownership_declaration()


def test_all_shipped_entity_ownership_declarations_are_complete() -> None:
    """CR-7 G-003/T-001/A-002..A-031: every shipped entity declares its state."""
    import importlib
    import pkgutil

    import plan_manager.domain as domain_pkg

    for module in pkgutil.iter_modules(domain_pkg.__path__):
        importlib.import_module(f"{domain_pkg.__name__}.{module.name}")

    def _subclasses(root):
        found = []
        for sub in root.__subclasses__():
            found.append(sub)
            found.extend(_subclasses(sub))
        return found

    declared = 0
    for cls in _subclasses(DataclassEntity):
        if (cls.__module__ or "").startswith("tests"):
            continue
        if not (cls.__module__ or "").startswith("plan_manager.domain."):
            continue
        if cls.__name__ in {"EntityIdentifier"}:
            continue
        cls.validate_ownership_declaration(require_ownership=True)
        declared += 1
    assert declared >= 31  # 30 per-entity AS targets + ToolsetMembership


# --------------------------------------------------------------------------
# CR-7 G-006/T-001/A-003: uniform soft-delete lifecycle on the direct engine
# surface. Point reads (crud_get/get_by_id) are unconditional; crud_list/
# crud_search hide marked rows behind one common include_marked flag
# (include_deleted kept as a deprecated alias); crud_soft_delete_recursive/
# crud_restore_recursive admit two independent closures on top of the
# explicit-only ordinary crud_soft_delete: include_children (ownership,
# OWNER_COLUMN) and include_related (relation index, source-depends-on-target
# only). Every test name below carries "soft_delete" so `-k soft_delete`
# selects this whole block.
# --------------------------------------------------------------------------


class _SearchableSoftDeleteProbe(_Probe):
    ENTITY_TYPE = "cr7_probe_soft_delete_searchable"
    SEARCH_COLUMNS = ("title",)


def test_soft_delete_crud_get_ignores_include_deleted_and_returns_marked_row() -> None:
    row_id = uuid.uuid4()
    row = {"uuid": row_id, "title": "x", "deleted_at": datetime.now(timezone.utc)}
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [row])])

    default_result = _Probe.crud_get(conn, row_id)
    excluding_result = _Probe.crud_get(conn, row_id, include_deleted=False)

    assert default_result is not None and default_result["uuid"] == row_id
    assert excluding_result is not None and excluding_result["uuid"] == row_id
    # No IS NULL guard on the soft-delete column: point reads are unconditional
    # regardless of include_deleted (CR-7 G-006/T-001/A-003). The column is
    # still SELECTed (it is a plain COLUMNS member); only the WHERE-clause
    # guard is gone.
    for sql_text, _ in conn.executed:
        assert '"deleted_at" IS NULL' not in sql_text


def test_soft_delete_get_by_id_matches_crud_get_unconditional_behaviour() -> None:
    row_id = uuid.uuid4()
    row = {"uuid": row_id, "title": "x", "deleted_at": datetime.now(timezone.utc)}
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [row])])

    result = _Probe.get_by_id(conn, row_id, include_deleted=False)
    assert result is not None and result["uuid"] == row_id


def test_soft_delete_crud_list_hides_marked_rows_by_default() -> None:
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _Probe.crud_list(conn)
    select_sql, _ = conn.executed[-1]
    assert '"deleted_at" IS NULL' in select_sql


def test_soft_delete_crud_list_include_marked_reveals_marked_rows() -> None:
    conn = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _Probe.crud_list(conn, include_marked=True)
    select_sql, _ = conn.executed[-1]
    assert '"deleted_at" IS NULL' not in select_sql


def test_soft_delete_crud_list_include_deleted_is_a_deprecated_alias() -> None:
    conn_true = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _Probe.crud_list(conn_true, include_deleted=True)
    assert '"deleted_at" IS NULL' not in conn_true.executed[-1][0]

    conn_false = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _Probe.crud_list(conn_false, include_deleted=False)
    assert '"deleted_at" IS NULL' in conn_false.executed[-1][0]

    # An explicit include_deleted always wins over the include_marked default,
    # both directions.
    conn_override = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _Probe.crud_list(conn_override, include_marked=True, include_deleted=False)
    assert '"deleted_at" IS NULL' in conn_override.executed[-1][0]


def test_soft_delete_crud_search_hides_marked_rows_unless_include_marked() -> None:
    conn_hidden = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _SearchableSoftDeleteProbe.crud_search(conn_hidden, search="x")
    assert '"deleted_at" IS NULL' in conn_hidden.executed[-1][0]

    conn_revealed = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _SearchableSoftDeleteProbe.crud_search(conn_revealed, search="x", include_marked=True)
    assert '"deleted_at" IS NULL' not in conn_revealed.executed[-1][0]

    conn_alias = _FakeConn(script=[(lambda sql: sql.startswith("SELECT"), [])])
    _SearchableSoftDeleteProbe.crud_search(conn_alias, search="x", include_deleted=True)
    assert '"deleted_at" IS NULL' not in conn_alias.executed[-1][0]


# --- Recursive admissions: include_children (ownership) / include_related
# --- (relation index), traversed via a small synthetic ownership+relation
# --- graph rather than the real domain package.


class _SDOwner(DataclassEntity):
    """Root of the fixture graph: an ordinary soft-deletable, owner-root kind."""

    ENTITY_TYPE = "cr7_sd_owner"
    TABLE_NAME = "calendar_entry"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "title", "updated_at", "deleted_at")
    UPDATE_COLUMNS = ("title",)
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"
    REGISTER_IDENTITY = False
    OWNER_ROOT = True


class _SDStep(DataclassEntity):
    """Owned by _SDOwner; declares no SOFT_DELETE_COLUMN, like the real step.py.

    Exists to prove traversal continues PAST a kind that opts out of soft
    delete entirely, as long as it carries a single ID_COLUMN to keep
    searching by (CR-7 G-006/T-001/A-003).
    """

    ENTITY_TYPE = "cr7_sd_step"
    TABLE_NAME = "step"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "owner_uuid")
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "owner_uuid"


class _SDGrandchild(DataclassEntity):
    """Owned by _SDStep -- two ownership hops below the root."""

    ENTITY_TYPE = "cr7_sd_grandchild"
    TABLE_NAME = "todo_item"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "owner_uuid", "updated_at", "deleted_at")
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "owner_uuid"


class _SDRelated(DataclassEntity):
    """Not owned by anything; reachable only via a relation-index triple that
    points AT _SDOwner (i.e. this row DEPENDS ON the owner)."""

    ENTITY_TYPE = "cr7_sd_related"
    TABLE_NAME = "wish_item"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "updated_at", "deleted_at")
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"
    REGISTER_IDENTITY = False
    OWNER_GAP = "test double: relation-index target only, no ownership edge"


class _GraphConn:
    """Answers the handful of query shapes the recursive walk issues, from an
    in-memory ownership+relation graph.

    Routes on the bound PARAMETER, not just the SQL text -- unlike the plain
    predicate-script fakes elsewhere in this file -- because telling apart
    "children of the root" from "children of the root's child" needs the id
    actually bound, not merely the query shape.
    """

    def __init__(self, *, children_by_table, relation_index, identities):
        self._children_by_table = children_by_table  # table -> {owner_id: [row, ...]}
        self._relation_index = relation_index  # target_id -> [(source_ref, target_ref, field_ref)]
        self._identities = identities  # id -> (table_name, entity_type)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        rendered = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        flat = " ".join(rendered.split())
        params = tuple(params)
        self.executed.append((flat, params))

        if flat.startswith("UPDATE"):
            table = flat.split('"')[1]
            row_id = params[-1]
            return _FakeCursor([{"uuid": row_id}])

        if flat.startswith("SELECT source_ref, target_ref, field_ref FROM relation_index"):
            (targets,) = params
            rows: list[tuple] = []
            for target in targets:
                rows.extend(self._relation_index.get(target, []))
            return _FakeCursor(rows)

        if flat.startswith("SELECT id, table_name, entity_type, created_at FROM entity_identity"):
            (ids,) = params
            rows = [
                (entity_id, *self._identities[entity_id], None)  # (id, table, type, created_at)
                for entity_id in ids
                if entity_id in self._identities
            ]
            return _FakeCursor(rows)

        if flat.startswith("SELECT") and 'FROM "' in flat:
            table = flat.split('FROM "', 1)[1].split('"', 1)[0]
            owner_value = params[-1] if params else None
            rows = self._children_by_table.get(table, {}).get(owner_value, [])
            return _FakeCursor(rows)

        return _FakeCursor([])


def _build_recursive_fixture(monkeypatch):
    """A 4-node graph: owner -> step -> grandchild (ownership, 2 hops through a
    non-soft-deletable node) and related -> owner (relation index only)."""
    import plan_manager.storage.reference_catalog as reference_catalog

    monkeypatch.setattr(
        reference_catalog,
        "_entity_classes",
        lambda: [_SDOwner, _SDStep, _SDGrandchild, _SDRelated],
    )

    owner_id, step_id, grandchild_id, related_id = (
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    )
    field_ref = uuid.uuid4()
    conn = _GraphConn(
        children_by_table={
            "step": {owner_id: [{"uuid": step_id, "owner_uuid": owner_id}]},
            "todo_item": {step_id: [{"uuid": grandchild_id, "owner_uuid": step_id}]},
        },
        relation_index={
            # related_id is the SOURCE, owner_id is the TARGET: related DEPENDS ON owner.
            owner_id: [(related_id, owner_id, field_ref)],
        },
        identities={related_id: ("wish_item", "cr7_sd_related")},
    )
    return conn, {
        "owner": owner_id,
        "step": step_id,
        "grandchild": grandchild_id,
        "related": related_id,
    }


def test_soft_delete_recursive_without_flags_marks_only_the_root(monkeypatch) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_soft_delete_recursive(conn, ids["owner"])
    assert [entry["row"]["uuid"] for entry in result["marked"]] == [ids["owner"]]
    assert result["skipped"] == []


def test_soft_delete_recursive_include_children_walks_past_a_non_deletable_node(
    monkeypatch,
) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_soft_delete_recursive(conn, ids["owner"], include_children=True)

    marked_ids = {entry["row"]["uuid"] for entry in result["marked"]}
    assert marked_ids == {ids["owner"], ids["grandchild"]}
    # _SDStep has no SOFT_DELETE_COLUMN: recorded as skipped, not marked, but
    # traversal still reached _SDGrandchild through it.
    assert [entry["table"] for entry in result["skipped"]] == ["step"]
    assert ids["related"] not in marked_ids  # include_related was off


def test_soft_delete_recursive_include_related_marks_only_the_dependent_row(
    monkeypatch,
) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_soft_delete_recursive(conn, ids["owner"], include_related=True)

    marked_ids = {entry["row"]["uuid"] for entry in result["marked"]}
    assert marked_ids == {ids["owner"], ids["related"]}
    assert result["skipped"] == []  # step/grandchild never probed: include_children was off


def test_soft_delete_recursive_related_traversal_queries_target_ref_only(
    monkeypatch,
) -> None:
    """The relation-index lookup must filter on target_ref (source depends on
    target), never source_ref (what the target itself points at)."""
    conn, ids = _build_recursive_fixture(monkeypatch)
    _SDOwner.crud_soft_delete_recursive(conn, ids["owner"], include_related=True)

    relation_calls = [sql for sql, _ in conn.executed if "relation_index" in sql]
    assert relation_calls  # the lookup did happen
    assert all(call.startswith("SELECT source_ref, target_ref, field_ref FROM relation_index WHERE target_ref = ANY")
               for call in relation_calls)
    assert not any("WHERE source_ref = ANY" in call for call in relation_calls)


def test_soft_delete_recursive_include_children_never_probes_owner_root_or_owner_gap_kinds(
    monkeypatch,
) -> None:
    """_SDOwner (OWNER_ROOT) and _SDRelated (OWNER_GAP) carry no OWNER_COLUMN,
    so include_children must never issue a children-lookup SELECT against
    their tables."""
    conn, ids = _build_recursive_fixture(monkeypatch)
    _SDOwner.crud_soft_delete_recursive(
        conn, ids["owner"], include_children=True, include_related=True
    )

    for sql_text, _ in conn.executed:
        if sql_text.startswith("SELECT") and 'FROM "calendar_entry"' in sql_text:
            pytest.fail(f"unexpected children-probe against calendar_entry: {sql_text}")
        if sql_text.startswith("SELECT") and 'FROM "wish_item"' in sql_text:
            pytest.fail(f"unexpected children-probe against wish_item: {sql_text}")


def test_soft_delete_recursive_include_children_and_include_related_together(
    monkeypatch,
) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_soft_delete_recursive(
        conn, ids["owner"], include_children=True, include_related=True
    )

    marked_ids = {entry["row"]["uuid"] for entry in result["marked"]}
    assert marked_ids == {ids["owner"], ids["grandchild"], ids["related"]}
    assert [entry["table"] for entry in result["skipped"]] == ["step"]


def test_restore_recursive_without_flags_restores_only_the_root(monkeypatch) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_restore_recursive(conn, ids["owner"])
    assert [entry["row"]["uuid"] for entry in result["restored"]] == [ids["owner"]]
    assert result["skipped"] == []
    update_sql, update_params = next(
        (sql, params) for sql, params in conn.executed if sql.startswith("UPDATE")
    )
    assert '"deleted_at" = %s' in update_sql
    assert update_params[0] is None  # restore clears the mark to NULL


def test_restore_recursive_honours_include_children_and_include_related_independently(
    monkeypatch,
) -> None:
    conn, ids = _build_recursive_fixture(monkeypatch)
    result = _SDOwner.crud_restore_recursive(
        conn, ids["owner"], include_children=True, include_related=True
    )

    restored_ids = {entry["row"]["uuid"] for entry in result["restored"]}
    assert restored_ids == {ids["owner"], ids["grandchild"], ids["related"]}
    assert [entry["table"] for entry in result["skipped"]] == ["step"]
    for sql_text, params in conn.executed:
        if sql_text.startswith("UPDATE"):
            assert params[0] is None  # every mark cleared, not backdated


def test_soft_delete_recursive_stays_explicit_only_ordinary_soft_delete(
    monkeypatch,
) -> None:
    """Ordinary crud_soft_delete never expands beyond the row named, even
    when the entity participates in the same ownership graph."""
    conn, ids = _build_recursive_fixture(monkeypatch)
    _SDOwner.crud_soft_delete(conn, ids["owner"])
    tables_touched = {sql.split('"')[1] for sql, _ in conn.executed if sql.startswith("UPDATE")}
    assert tables_touched == {"calendar_entry"}
    assert not any(sql.startswith("SELECT") for sql, _ in conn.executed)
