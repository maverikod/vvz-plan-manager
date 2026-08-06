"""Regression suite for CR-7 G-006/T-002/A-001: the reference repair surface.

Fake psycopg connections and monkeypatched collaborators throughout -- no
live database, matching tests/test_runtime_hard_delete_set_wise.py and
tests/storage/test_relation_index_store.py's conventions for this package.

The seventeen-reference fixture in
test_find_dangling_references_classifies_all_seventeen is the acceptance
material the frozen step names ("the operations must classify all
seventeen"); it plants one dangling value per catalogued single-uuid column,
chosen to span every nullability verdict (nullable, not_nullable, unknown)
that plan_manager.storage.reference_repair_store.nullability_for actually
produces against the REAL REFERENCE_CATALOG and REAL entity descriptors --
the live seventeen-dangling-reference count is acceptance material for the
later live run, not reproduced here.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest

# reference_repair_store must be imported before identity_audit in this file:
# identity.py and identity_audit.py import from each other (identity_audit's
# re-export at the bottom of identity.py), and that cycle only resolves when
# identity.py is entered first -- which reference_repair_store's own import
# chain (identity -> resolve_entity_identities_batch) guarantees.
import plan_manager.storage.reference_repair_store as rrs
import plan_manager.storage.identity_audit as identity_audit_module
import plan_manager.storage.runtime_hard_delete as rhd
from plan_manager.storage.reference_catalog import REFERENCE_CATALOG


# ---------------------------------------------------------------------------
# Fake connection plumbing (shared shape with the sibling CR-7 suites).
# ---------------------------------------------------------------------------


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


def _statement_text(query: Any) -> str:
    return query.as_string(None) if hasattr(query, "as_string") else str(query)


class _FakeConn:
    """Records every statement; answers a find-style scan from a keyed row map."""

    _SCAN_RE = re.compile(r"SELECT uuid, (\w+) FROM (\w+) WHERE \1 IS NOT NULL")

    def __init__(self, rows_by_key: dict[tuple[str, str], list[tuple[Any, Any]]] | None = None) -> None:
        self.rows_by_key = rows_by_key or {}
        self.statements: list[tuple[str, list[Any]]] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = _statement_text(query)
        self.statements.append((text, list(params) if params is not None else []))
        match = self._SCAN_RE.search(text)
        if match:
            column, table = match.group(1), match.group(2)
            return _FakeCursor(self.rows_by_key.get((table, column), []))
        return _FakeCursor([])

    @property
    def updates(self) -> list[tuple[str, list[Any]]]:
        return [(text, params) for text, params in self.statements if text.strip().startswith("UPDATE")]


def _never_resolves(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Fake resolve_entity_identities_batch: nothing ever resolves (all dangling)."""
    return {}


# ---------------------------------------------------------------------------
# nullability_for
# ---------------------------------------------------------------------------


def test_nullable_field_reports_nullable() -> None:
    # TodoItem.anchor_plan_uuid: uuid.UUID | None.
    assert rrs.nullability_for("todo_item", "anchor_plan_uuid") == rrs.NULLABLE


def test_non_optional_field_reports_not_nullable() -> None:
    # ExecutionAttempt.plan_uuid: uuid.UUID (no | None).
    assert rrs.nullability_for("execution_attempt", "plan_uuid") == rrs.NOT_NULLABLE


def test_table_with_no_addressable_entity_class_reports_unknown() -> None:
    # Paragraph.TABLE_NAME is None: paragraph rows are not addressed through
    # the entity-class registry this lookup walks.
    assert rrs.nullability_for("paragraph", "plan_uuid") == rrs.UNKNOWN


def test_composite_keyed_source_without_the_field_declared_reports_unknown() -> None:
    # Relation/Concept do not declare "plan_uuid" as a dataclass field of
    # their own (composite ID_COLUMNS); the column is schema-NOT-NULL but
    # this module has no static way to see that, so it answers UNKNOWN.
    assert rrs.nullability_for("relation", "plan_uuid") == rrs.UNKNOWN
    assert rrs.nullability_for("concept", "plan_uuid") == rrs.UNKNOWN


def test_unknown_table_name_reports_unknown() -> None:
    assert rrs.nullability_for("no_such_table", "no_such_column") == rrs.UNKNOWN


# ---------------------------------------------------------------------------
# find_dangling_references: the seventeen-reference acceptance fixture.
# ---------------------------------------------------------------------------

# Chosen against the REAL catalog/descriptors (verified interactively against
# nullability_for), spanning all three verdicts: six NULLABLE columns
# (repairable by clear_reference), six NOT_NULLABLE columns and five UNKNOWN
# columns (both irreparable by clear -- only delete_carrier can resolve them).
_SEVENTEEN_COLUMNS: tuple[tuple[str, str], ...] = (
    # nullable (6)
    ("todo_item", "anchor_plan_uuid"),
    ("todo_item", "anchor_step_uuid"),
    ("escalation", "anchor_step_uuid"),
    ("runtime_comment", "supersedes_comment_uuid"),
    ("bug_report", "duplicate_of_uuid"),
    ("step", "parent_step_uuid"),
    # not_nullable (6)
    ("execution_attempt", "plan_uuid"),
    ("execution_attempt", "step_uuid"),
    ("bug_impact", "bug_uuid"),
    ("bug_fix", "bug_uuid"),
    ("toolset_membership", "tool_uuid"),
    ("model", "provider_uuid"),
    # unknown (5)
    ("paragraph", "plan_uuid"),
    ("concept", "plan_uuid"),
    ("relation", "plan_uuid"),
    ("cascade", "plan_uuid"),
    ("node_version", "plan_uuid"),
)


def test_seventeen_columns_span_every_nullability_verdict() -> None:
    """Sanity check on the fixture itself: every chosen column is catalogued,
    and the three groups above genuinely match what nullability_for reports
    against the real descriptors -- this guards the fixture against silent
    drift if an entity descriptor's type hint ever changes."""
    assert len(_SEVENTEEN_COLUMNS) == 17
    assert len(set(_SEVENTEEN_COLUMNS)) == 17, "fixture columns must be distinct"
    for table, column in _SEVENTEEN_COLUMNS:
        assert (table, column) in REFERENCE_CATALOG, f"not catalogued: {table}.{column}"
    verdicts = {pair: rrs.nullability_for(*pair) for pair in _SEVENTEEN_COLUMNS}
    assert list(verdicts.values())[:6] == [rrs.NULLABLE] * 6
    assert list(verdicts.values())[6:12] == [rrs.NOT_NULLABLE] * 6
    assert list(verdicts.values())[12:] == [rrs.UNKNOWN] * 5


def test_find_dangling_references_classifies_all_seventeen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rrs, "resolve_entity_identities_batch", _never_resolves)

    planted: dict[tuple[uuid.UUID, uuid.UUID], tuple[str, str]] = {}
    rows_by_key: dict[tuple[str, str], list[tuple[Any, Any]]] = {}
    for table, column in _SEVENTEEN_COLUMNS:
        source_ref, missing_target = uuid.uuid4(), uuid.uuid4()
        rows_by_key[(table, column)] = [(source_ref, missing_target)]
        planted[(source_ref, missing_target)] = (table, column)

    conn = _FakeConn(rows_by_key=rows_by_key)
    findings = rrs.find_dangling_references(conn)

    assert len(findings) == 17, f"expected 17 dangling references, found {len(findings)}"

    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for finding in findings:
        key = (finding["source_ref"], finding["missing_target"])
        assert key in planted, f"unexpected finding: {finding}"
        expected_table, expected_column = planted[key]
        assert finding["source_table"] == expected_table
        assert finding["source_column"] == expected_column
        assert finding["property_name"] == expected_column
        assert finding["nullability"] == rrs.nullability_for(expected_table, expected_column)
        assert finding["target_table"] == REFERENCE_CATALOG[(expected_table, expected_column)].target_table
        seen.add(key)

    assert seen == set(planted), "every planted dangling reference must be classified exactly once"

    # Nullability distribution matches the fixture's own three groups.
    by_verdict: dict[str, int] = {}
    for finding in findings:
        by_verdict[finding["nullability"]] = by_verdict.get(finding["nullability"], 0) + 1
    assert by_verdict == {rrs.NULLABLE: 6, rrs.NOT_NULLABLE: 6, rrs.UNKNOWN: 5}


def test_find_dangling_references_skips_a_resolvable_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A target value the registry DOES resolve is not a dangling reference."""
    live_ref = uuid.uuid4()

    def _resolves_everything(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        return {entity_id: {"entity_type": "plan"} for entity_id in ids}

    monkeypatch.setattr(rrs, "resolve_entity_identities_batch", _resolves_everything)
    conn = _FakeConn(rows_by_key={("todo_item", "anchor_plan_uuid"): [(uuid.uuid4(), live_ref)]})

    findings = rrs.find_dangling_references(conn)

    assert findings == []


def test_find_dangling_references_tolerates_a_missing_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scan failure (missing table/column in this schema) is skipped, not raised."""

    class _RaisingConn(_FakeConn):
        def execute(self, query: Any, params: Any = None) -> _FakeCursor:
            text = _statement_text(query)
            if self._SCAN_RE.search(text):
                raise RuntimeError("relation does not exist")
            return super().execute(query, params)

    monkeypatch.setattr(rrs, "resolve_entity_identities_batch", _never_resolves)
    findings = rrs.find_dangling_references(_RaisingConn())

    assert findings == []


# ---------------------------------------------------------------------------
# clear_reference
# ---------------------------------------------------------------------------


def test_clear_reference_nulls_the_column_and_retires_the_triple(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def _spy_record_reference(conn: Any, *, source_ref: Any, target_ref: Any, property_name: str) -> None:
        calls.append({"source_ref": source_ref, "target_ref": target_ref, "property_name": property_name})
        return None

    monkeypatch.setattr(rrs, "record_reference", _spy_record_reference)
    conn = _FakeConn()
    source_ref = uuid.uuid4()

    result = rrs.clear_reference(
        conn, source_table="todo_item", source_column="anchor_plan_uuid", source_ref=source_ref
    )

    assert result == {
        "source_table": "todo_item",
        "source_column": "anchor_plan_uuid",
        "source_ref": source_ref,
        "cleared": True,
    }
    assert len(conn.updates) == 1
    update_text, update_params = conn.updates[0]
    assert '"todo_item"' in update_text
    assert '"anchor_plan_uuid"' in update_text
    assert "= NULL" in update_text
    assert update_params == [source_ref]
    assert calls == [{"source_ref": source_ref, "target_ref": None, "property_name": "anchor_plan_uuid"}]


def test_clear_reference_refuses_a_not_nullable_column(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(rrs, "record_reference", lambda *a, **kw: calls.append((a, kw)))
    conn = _FakeConn()

    with pytest.raises(PermissionError):
        rrs.clear_reference(
            conn, source_table="execution_attempt", source_column="plan_uuid", source_ref=uuid.uuid4()
        )

    assert conn.updates == [], "a refused clear must never touch the row"
    assert calls == [], "a refused clear must never touch the relation index"


def test_clear_reference_refuses_an_unknown_nullability_column(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = _FakeConn()
    with pytest.raises(PermissionError):
        rrs.clear_reference(conn, source_table="paragraph", source_column="plan_uuid", source_ref=uuid.uuid4())
    assert conn.updates == []


def test_clear_reference_raises_key_error_for_an_uncatalogued_column() -> None:
    conn = _FakeConn()
    with pytest.raises(KeyError):
        rrs.clear_reference(conn, source_table="todo_item", source_column="not_a_real_column", source_ref=uuid.uuid4())
    assert conn.updates == []


# ---------------------------------------------------------------------------
# delete_carrier
# ---------------------------------------------------------------------------


def test_delete_carrier_dry_run_reports_admissible_closure_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier_id = uuid.uuid4()

    monkeypatch.setattr(
        rrs,
        "resolve_entity_identities_batch",
        lambda conn, ids: {entity_id: {"entity_type": "todo"} for entity_id in ids if entity_id == carrier_id},
    )
    monkeypatch.setattr(rrs, "referrers_of", lambda conn, targets: [])

    conn = _FakeConn()
    result = rrs.delete_carrier(conn, [carrier_id], dry_run=True)

    assert result == {
        "dry_run": True,
        "would_remove": [carrier_id],
        "blocked_by": [],
        "unresolved": [],
        "admissible": True,
    }
    assert conn.statements == [], "a dry run must never write or even read the base tables"


def test_delete_carrier_dry_run_reports_an_unmarked_referrer_as_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier_id = uuid.uuid4()
    unmarked_referrer = uuid.uuid4()
    triple = {"source_ref": unmarked_referrer, "target_ref": carrier_id, "field_ref": uuid.uuid4()}

    def _resolve(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        known = {carrier_id: "todo", unmarked_referrer: "bug"}
        return {entity_id: {"entity_type": known[entity_id]} for entity_id in ids if entity_id in known}

    def _referrers_of(conn: Any, targets: Any) -> list[dict[str, Any]]:
        targets = set(targets)
        return [triple] if triple["target_ref"] in targets else []

    monkeypatch.setattr(rrs, "resolve_entity_identities_batch", _resolve)
    monkeypatch.setattr(rrs, "referrers_of", _referrers_of)
    monkeypatch.setattr(rhd, "_is_marked", lambda conn, cls, entity_id: False)

    result = rrs.delete_carrier(_FakeConn(), [carrier_id], dry_run=True)

    assert result["would_remove"] == [carrier_id]
    assert result["blocked_by"] == [triple]
    assert result["admissible"] is False
    assert result["unresolved"] == []


def test_delete_carrier_dry_run_sweeps_in_a_marked_referrer(monkeypatch: pytest.MonkeyPatch) -> None:
    carrier_id = uuid.uuid4()
    marked_referrer = uuid.uuid4()
    triple = {"source_ref": marked_referrer, "target_ref": carrier_id, "field_ref": uuid.uuid4()}

    def _resolve(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        known = {carrier_id: "todo", marked_referrer: "comment"}
        return {entity_id: {"entity_type": known[entity_id]} for entity_id in ids if entity_id in known}

    def _referrers_of(conn: Any, targets: Any) -> list[dict[str, Any]]:
        targets = set(targets)
        return [triple] if triple["target_ref"] in targets else []

    monkeypatch.setattr(rrs, "resolve_entity_identities_batch", _resolve)
    monkeypatch.setattr(rrs, "referrers_of", _referrers_of)
    monkeypatch.setattr(rhd, "_is_marked", lambda conn, cls, entity_id: entity_id == marked_referrer)

    result = rrs.delete_carrier(_FakeConn(), [carrier_id], dry_run=True)

    assert set(result["would_remove"]) == {carrier_id, marked_referrer}
    assert result["blocked_by"] == []
    assert result["admissible"] is True


def test_delete_carrier_live_delegates_to_the_set_wise_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    carrier_id = uuid.uuid4()
    calls: list[tuple[Any, Any]] = []

    def _fake_hard_delete_marked_set(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        calls.append((list(entity_ids), changed_by))
        return {"removed": [carrier_id]}

    monkeypatch.setattr(rhd, "hard_delete_marked_set", _fake_hard_delete_marked_set)

    result = rrs.delete_carrier(_FakeConn(), [carrier_id], dry_run=False, changed_by="repair-bot")

    assert result == {"dry_run": False, "removed": [carrier_id]}
    assert calls == [([carrier_id], "repair-bot")]


# ---------------------------------------------------------------------------
# Registry recovery (C-009).
# ---------------------------------------------------------------------------


def test_audit_registry_and_restore_missing_identities_are_direct_delegates() -> None:
    """No duplicated logic: these are the identity_audit primitives themselves."""
    assert rrs.audit_registry is identity_audit_module.audit_registry
    assert rrs.restore_missing_identities is identity_audit_module.restore_missing_identities


def test_remove_unreferenced_extra_identities_batches_the_single_id_primitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept_id, removable_id = uuid.uuid4(), uuid.uuid4()
    report = {
        "missing": [],
        "extra": [{"id": kept_id, "table_name": "todo_item"}, {"id": removable_id, "table_name": "bug_report"}],
        "conflicts": [],
        "unscanned": [],
    }

    def _fake_remove(conn: Any, entity_id: Any) -> bool:
        return entity_id == removable_id

    monkeypatch.setattr(rrs, "remove_extra_identity_if_unreferenced", _fake_remove)

    result = rrs.remove_unreferenced_extra_identities(_FakeConn(), audit_report=report)

    assert result == {"removed": [removable_id], "retained": [kept_id]}


def test_remove_unreferenced_extra_identities_runs_its_own_audit_when_none_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra_id = uuid.uuid4()
    calls: list[Any] = []

    monkeypatch.setattr(
        rrs,
        "audit_registry",
        lambda conn: {"missing": [], "extra": [{"id": extra_id, "table_name": "todo_item"}], "conflicts": [], "unscanned": []},
    )

    def _fake_remove(conn: Any, entity_id: Any) -> bool:
        calls.append(entity_id)
        return True

    monkeypatch.setattr(rrs, "remove_extra_identity_if_unreferenced", _fake_remove)

    result = rrs.remove_unreferenced_extra_identities(_FakeConn())

    assert calls == [extra_id]
    assert result == {"removed": [extra_id], "retained": []}


def test_rebuild_relation_index_computes_then_replaces_atomically(monkeypatch: pytest.MonkeyPatch) -> None:
    triple = (uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    calls: list[str] = []

    def _fake_compute(conn: Any) -> set[Any]:
        calls.append("compute")
        return {triple}

    def _fake_replace(conn: Any, triples: Any) -> int:
        calls.append("replace")
        assert set(triples) == {triple}
        return 1

    monkeypatch.setattr(rrs, "compute_canonical_triples", _fake_compute)
    monkeypatch.setattr(rrs, "replace_index", _fake_replace)

    result = rrs.rebuild_relation_index(_FakeConn())

    assert result == {"written": 1}
    assert calls == ["compute", "replace"]
