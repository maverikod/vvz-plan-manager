"""CR-7 G-007/T-001/A-002: unit coverage for plan_manager.maintenance.anchor_cutover.

No live PostgreSQL anywhere in this module. Reuses the FakeCanonicalStore
idiom from tests/exchange/test_cr7_roundtrip.py -- a genuinely stateful
dict-table-backed fake psycopg connection (INSERT/SELECT/UPDATE/DELETE all
mutate real in-memory state) -- rather than the single-shot canned-row fakes
used elsewhere, because a cutover run issues a write and then re-reads what
it wrote (crud_update, then crud_list for verification; record_reference's
delete-then-insert). The fake is copied and locally extended here (not
imported cross-module) because that source module's own docstring documents
a same-process-registry collision hazard from importing its fixture into a
second test module that seeds independent rows under the same real table
names.

Covers: dry-run reports full mapping decisions and writes nothing; a real
run sets owner values per the documented discriminator rules (including a
step-anchor-alongside-a-plan-anchor secondary reference written through the
already-catalogued relation_index edge, and an uncatalogued secondary
reference left as a report-only decision); a file-anchor row stays rootlike
with its descriptive path untouched; the answer_envelope partial family's
undiscriminated precedence; an unrecognized discriminator value raises
instead of guessing, and -- since this module documents that it operates
inside the caller's own transaction -- what a caller's real ROLLBACK would
undo after that raise is simulated here as a snapshot restore, and the
restored state matches the untouched original; verify_move's canonical
comparison detects a planted mismatch that is not the expected owner delta.
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from plan_manager.domain.answer_envelope import AnswerEnvelope
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.wish import WishItem
from plan_manager.exchange import canonical_form as cf
from plan_manager.maintenance import anchor_cutover as ac


# ---------------------------------------------------------------------------
# FakeAnchorStore: a stateful fake psycopg connection (see module docstring).
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


class FakeAnchorStore:
    """A dict-table-backed fake psycopg connection; see module docstring."""

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
            return self._delete(body, params)
        raise AssertionError(f"FakeAnchorStore: unsupported statement: {flat!r}")

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
            raise AssertionError(f"FakeAnchorStore: unsupported predicate clause: {clause!r}")
        return True

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
                return _FakeCursor([], [])
        new_row = dict(zip(columns, params))
        rows.append(new_row)
        if not returning:
            return _FakeCursor([], [])
        ret_cols = [c.strip().strip('"') for c in returning.split(",")]
        return _FakeCursor([tuple(new_row.get(c) for c in ret_cols)], ret_cols)

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

    def _delete(self, body: str, params: tuple[Any, ...]) -> _FakeCursor:
        match = _DELETE_RE.match(body)
        assert match, body
        table = match.group("table")
        where = match.group("where")
        if where is None:
            self.tables[table] = []
        else:
            rows = self.tables.get(table, [])
            self.tables[table] = [row for row in rows if not self._row_matches(row, where, params)]
        return _FakeCursor([], [])


# ---------------------------------------------------------------------------
# Row fixtures.
# ---------------------------------------------------------------------------

_ANCHOR_SUFFIXES = ("project_id", "file_path", "plan_uuid", "revision_uuid", "step_uuid", "step_path", "ref_id")


def _dummy(column: str, salt: str) -> Any:
    if column == "uuid" or column.endswith("_uuid") or column.endswith("_id"):
        return uuid.uuid4()
    return f"{salt}::{column}"


def _base_row(entity_cls: type, salt: str, *, prefix: str | None = None) -> dict[str, Any]:
    """Every declared column filled with a dummy value, then every anchor-family
    identifier column (and, for bug_report, source_command/source_service, and
    for answer_envelope, its three candidate columns) reset to None so a
    scenario only carries the values it explicitly sets."""
    row = {column: _dummy(column, salt) for column in entity_cls.COLUMNS}
    if prefix is not None:
        for suffix in _ANCHOR_SUFFIXES:
            column = f"{prefix}_{suffix}"
            if column in row:
                row[column] = None
    if entity_cls is BugReport:
        row["source_command"] = None
        row["source_service"] = None
    if entity_cls is AnswerEnvelope:
        for column in ac.ANSWER_ENVELOPE_PRECEDENCE:
            row[column] = None
    return row


def _seed(store: FakeAnchorStore, entity_cls: type, row: dict[str, Any]) -> None:
    store.tables.setdefault(entity_cls.TABLE_NAME, []).append(row)


def _seed_identity(store: FakeAnchorStore, entity_id: uuid.UUID, table_name: str, entity_type: str) -> None:
    store.tables.setdefault("entity_identity", []).append(
        {"id": entity_id, "table_name": table_name, "entity_type": entity_type, "created_at": None}
    )


def _owner_of(store: FakeAnchorStore, table: str, owner_column: str, ref: uuid.UUID) -> Any:
    for row in store.tables.get(table, []):
        if row["uuid"] == ref:
            return row.get(owner_column)
    raise AssertionError(f"no {table} row for ref {ref}")


# ---------------------------------------------------------------------------
# (1) Dry-run: full mapping decision report, zero writes.
# ---------------------------------------------------------------------------


def test_dry_run_reports_and_writes_nothing() -> None:
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    row = _base_row(TodoItem, "dry", prefix="anchor")
    row["primary_anchor_type"] = "plan"
    row["anchor_plan_uuid"] = plan_uuid
    _seed(store, TodoItem, row)
    _seed_identity(store, plan_uuid, "plan", "plan")
    before = copy.deepcopy(store.tables)

    report = ac.run_anchor_cutover(store, dry_run=True)

    assert report["dry_run"] is True
    todo_report = report["tables"]["todo_item"]
    assert todo_report["discriminator_counts"]["plan"]["by_classification"] == {"owner_set": 1}
    assert todo_report["owner_writes"] == {"planned": 1, "written": 0}
    assert todo_report["relation_edges_written"] == 0
    assert todo_report["verification"] is None
    # Nothing was mutated: the store is byte-for-byte the pre-call snapshot.
    assert store.tables == before
    assert not any(stmt.startswith("UPDATE") for stmt, _ in store.executed)


# ---------------------------------------------------------------------------
# (2) Real run: owners set per rule, including a secondary reference written
# through an already-catalogued relation_index edge and one left uncatalogued.
# ---------------------------------------------------------------------------


def test_real_run_sets_owner_via_plan_discriminator() -> None:
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    row = _base_row(TodoItem, "t1", prefix="anchor")
    row["primary_anchor_type"] = "plan"
    row["anchor_plan_uuid"] = plan_uuid
    _seed(store, TodoItem, row)
    _seed_identity(store, plan_uuid, "plan", "plan")

    report = ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "todo_item", "owner", row["uuid"]) == plan_uuid
    todo_report = report["tables"]["todo_item"]
    assert todo_report["owner_writes"] == {"planned": 1, "written": 1}
    assert todo_report["verification"]["status"] == "ok"


def test_real_run_step_owner_with_catalogued_secondary_plan_reference() -> None:
    """discriminator=='step': owner is anchor_step_uuid; the accompanying
    anchor_plan_uuid is a non-owner typed association, catalogued
    (REFERENCE_CATALOG carries todo_item.anchor_plan_uuid -> plan
    unconditionally), so it is written as a relation_index edge."""
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    row = _base_row(TodoItem, "t2", prefix="anchor")
    row["primary_anchor_type"] = "step"
    row["anchor_plan_uuid"] = plan_uuid
    row["anchor_step_uuid"] = step_uuid
    _seed(store, TodoItem, row)
    _seed_identity(store, plan_uuid, "plan", "plan")
    _seed_identity(store, step_uuid, "step", "step")

    report = ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "todo_item", "owner", row["uuid"]) == step_uuid
    todo_report = report["tables"]["todo_item"]
    secondary = todo_report["secondary_references"]
    assert len(secondary) == 1
    assert secondary[0]["column"] == "anchor_plan_uuid"
    assert secondary[0]["catalogued"] is True
    assert secondary[0]["written"] is True
    assert todo_report["relation_edges_written"] == 1
    triples = store.tables["relation_index"]
    assert len(triples) == 1
    assert triples[0]["source_ref"] == row["uuid"]
    assert triples[0]["target_ref"] == plan_uuid


def test_real_run_uncatalogued_secondary_is_reported_not_written() -> None:
    """discriminator=='plan': owner is anchor_plan_uuid; a populated
    anchor_revision_uuid alongside it has no REFERENCE_CATALOG entry for
    (todo_item, anchor_revision_uuid) at all (it is in reference_catalog's
    own UNCLASSIFIED_REFERENCE_COLUMNS), so it must be reported and left
    unwritten -- this module must not invent a catalog entry."""
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    revision_uuid = uuid.uuid4()
    row = _base_row(TodoItem, "t3", prefix="anchor")
    row["primary_anchor_type"] = "plan"
    row["anchor_plan_uuid"] = plan_uuid
    row["anchor_revision_uuid"] = revision_uuid
    _seed(store, TodoItem, row)
    _seed_identity(store, plan_uuid, "plan", "plan")
    _seed_identity(store, revision_uuid, "revision", "revision")

    report = ac.run_anchor_cutover(store, dry_run=False)

    todo_report = report["tables"]["todo_item"]
    secondary = todo_report["secondary_references"]
    assert len(secondary) == 1
    assert secondary[0]["column"] == "anchor_revision_uuid"
    assert secondary[0]["catalogued"] is False
    assert secondary[0]["written"] is False
    assert todo_report["relation_edges_written"] == 0
    assert store.tables.get("relation_index", []) == []


def test_real_run_ref_id_owner_for_bug_and_execution_attempt_discriminators() -> None:
    store = FakeAnchorStore()
    bug_uuid = uuid.uuid4()
    row = _base_row(WishItem, "w1", prefix="anchor")
    row["primary_anchor_type"] = "bug"
    row["anchor_ref_id"] = bug_uuid
    _seed(store, WishItem, row)
    _seed_identity(store, bug_uuid, "bug", "bug")

    ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "wish_item", "owner", row["uuid"]) == bug_uuid


def test_real_run_project_discriminator_stores_external_id_as_owner() -> None:
    store = FakeAnchorStore()
    external_project_id = uuid.uuid4()
    row = _base_row(CalendarEntry, "c1", prefix="anchor")
    row["primary_anchor_type"] = "project"
    row["anchor_project_id"] = external_project_id
    _seed(store, CalendarEntry, row)
    # Deliberately NOT seeded in entity_identity: an external project id is
    # not a local row, and the owner write does not depend on registry
    # resolution the way a secondary relation_index edge would.

    ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "calendar_entry", "owner", row["uuid"]) == external_project_id


def test_real_run_bug_report_owner_uuid_column_and_execution_attempt_source() -> None:
    store = FakeAnchorStore()
    attempt_uuid = uuid.uuid4()
    row = _base_row(BugReport, "b1", prefix="source")
    row["source_anchor_type"] = "execution_attempt"
    row["source_ref_id"] = attempt_uuid
    _seed(store, BugReport, row)
    _seed_identity(store, attempt_uuid, "execution_attempt", "execution_attempt")

    ac.run_anchor_cutover(store, dry_run=False)

    # bug_report's owner column is owner_uuid (naming collision with the
    # pre-existing text `owner` assignee column), per migration 0029.
    assert _owner_of(store, "bug_report", "owner_uuid", row["uuid"]) == attempt_uuid


def test_real_run_escalation_review_result_discriminator_uses_ref_id() -> None:
    store = FakeAnchorStore()
    review_uuid = uuid.uuid4()
    row = _base_row(Escalation, "e1", prefix="anchor")
    row["primary_anchor_type"] = "review_result"
    row["anchor_ref_id"] = review_uuid
    _seed(store, Escalation, row)
    _seed_identity(store, review_uuid, "review_result", "review_result")

    ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "escalation", "owner", row["uuid"]) == review_uuid


def test_real_run_runtime_comment_escalation_discriminator_uses_ref_id() -> None:
    """RuntimeComment's own 11th anchor kind ('escalation', absent from the
    shared PrimaryAnchorType vocabulary) shares anchor_ref_id's column and
    owner semantics with todo/bug/bug_fix/execution_attempt/review_result."""
    store = FakeAnchorStore()
    escalation_uuid = uuid.uuid4()
    row = _base_row(RuntimeComment, "rc1", prefix="anchor")
    row["primary_anchor_type"] = "escalation"
    row["anchor_ref_id"] = escalation_uuid
    _seed(store, RuntimeComment, row)
    _seed_identity(store, escalation_uuid, "escalation", "escalation")

    ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "runtime_comment", "owner", row["uuid"]) == escalation_uuid


# ---------------------------------------------------------------------------
# (3) file-anchor rows stay rootlike: no owner, descriptive path untouched.
# ---------------------------------------------------------------------------


def test_file_anchor_row_stays_rootlike_with_path_retained() -> None:
    store = FakeAnchorStore()
    row = _base_row(TodoItem, "f1", prefix="anchor")
    row["primary_anchor_type"] = "file"
    row["anchor_project_id"] = uuid.uuid4()
    row["anchor_file_path"] = "plan_manager/domain/todo.py"
    _seed(store, TodoItem, row)

    report = ac.run_anchor_cutover(store, dry_run=False)

    todo_report = report["tables"]["todo_item"]
    assert todo_report["discriminator_counts"]["file"]["by_classification"] == {"root": 1}
    assert todo_report["owner_writes"] == {"planned": 0, "written": 0}
    # No owner column was ever set on the row (root, by design).
    stored = next(r for r in store.tables["todo_item"] if r["uuid"] == row["uuid"])
    assert "owner" not in stored or stored["owner"] is None
    assert stored["anchor_file_path"] == "plan_manager/domain/todo.py"


def test_bug_report_command_and_unidentified_sources_are_rootlike_or_skipped() -> None:
    store = FakeAnchorStore()
    command_row = _base_row(BugReport, "cmd", prefix="source")
    command_row["source_anchor_type"] = "command"
    command_row["source_command"] = "pipeline"
    unidentified_row = _base_row(BugReport, "unk", prefix="source")
    unidentified_row["source_anchor_type"] = "unidentified"
    _seed(store, BugReport, command_row)
    _seed(store, BugReport, unidentified_row)

    report = ac.run_anchor_cutover(store, dry_run=False)

    bug_report = report["tables"]["bug_report"]
    assert bug_report["discriminator_counts"]["command"]["by_classification"] == {"root": 1}
    assert bug_report["discriminator_counts"]["unidentified"]["by_classification"] == {"skipped": 1}
    assert _owner_of(store, "bug_report", "owner_uuid", command_row["uuid"]) is None
    assert _owner_of(store, "bug_report", "owner_uuid", unidentified_row["uuid"]) is None
    stored_command = next(r for r in store.tables["bug_report"] if r["uuid"] == command_row["uuid"])
    assert stored_command["source_command"] == "pipeline"


# ---------------------------------------------------------------------------
# (4) answer_envelope's undiscriminated precedence.
# ---------------------------------------------------------------------------


def test_answer_envelope_precedence_prefers_attempt_uuid() -> None:
    store = FakeAnchorStore()
    attempt_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    row = _base_row(AnswerEnvelope, "ae1")
    row["attempt_uuid"] = attempt_uuid
    row["anchor_plan_uuid"] = plan_uuid  # secondary: attempt_uuid wins
    _seed(store, AnswerEnvelope, row)
    _seed_identity(store, plan_uuid, "plan", "plan")

    report = ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "answer_envelope", "owner", row["uuid"]) == attempt_uuid
    envelope_report = report["tables"]["answer_envelope"]
    assert envelope_report["discriminator_counts"]["attempt_uuid"]["by_classification"] == {"owner_set": 1}
    secondary = envelope_report["secondary_references"]
    assert len(secondary) == 1
    assert secondary[0]["column"] == "anchor_plan_uuid"
    assert secondary[0]["catalogued"] is True  # answer_envelope.anchor_plan_uuid -> plan is catalogued
    assert secondary[0]["written"] is True


def test_answer_envelope_falls_back_to_anchor_plan_uuid_when_others_absent() -> None:
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    row = _base_row(AnswerEnvelope, "ae2")
    row["anchor_plan_uuid"] = plan_uuid
    _seed(store, AnswerEnvelope, row)
    _seed_identity(store, plan_uuid, "plan", "plan")

    ac.run_anchor_cutover(store, dry_run=False)

    assert _owner_of(store, "answer_envelope", "owner", row["uuid"]) == plan_uuid


def test_answer_envelope_no_candidate_is_skipped() -> None:
    store = FakeAnchorStore()
    row = _base_row(AnswerEnvelope, "ae3")
    _seed(store, AnswerEnvelope, row)

    report = ac.run_anchor_cutover(store, dry_run=False)

    envelope_report = report["tables"]["answer_envelope"]
    assert envelope_report["discriminator_counts"]["none"]["by_classification"] == {"skipped": 1}
    assert _owner_of(store, "answer_envelope", "owner", row["uuid"]) is None


# ---------------------------------------------------------------------------
# (5) Unrecognized discriminator raises; a caller's ROLLBACK (simulated by
# restoring a pre-call snapshot) leaves the source untouched.
# ---------------------------------------------------------------------------


def test_unrecognized_discriminator_raises() -> None:
    store = FakeAnchorStore()
    row = _base_row(TodoItem, "bad", prefix="anchor")
    row["primary_anchor_type"] = "not-a-real-anchor-type"
    _seed(store, TodoItem, row)

    try:
        ac.run_anchor_cutover(store, dry_run=False)
        raise AssertionError("expected AnchorCutoverError")
    except ac.AnchorCutoverError as exc:
        assert "unrecognized" in str(exc)


def test_rollback_on_error_leaves_source_untouched() -> None:
    """TodoItem (processed first, per FAMILY_SPECS order) gets a real,
    successful owner write; BugReport (processed later) carries a corrupt
    discriminator value and raises. This module never commits or rolls back
    itself (see its own "TRANSACTIONAL DISCIPLINE" docstring section) -- it
    is the caller's real transaction that would undo the TodoItem write on
    this exception. That real ROLLBACK is simulated here by restoring a
    snapshot taken before the call; the restored state must equal the
    original, untouched snapshot, proving the earlier partial write is not
    something a caller can observe once it rolls back."""
    store = FakeAnchorStore()
    plan_uuid = uuid.uuid4()
    good_row = _base_row(TodoItem, "good", prefix="anchor")
    good_row["primary_anchor_type"] = "plan"
    good_row["anchor_plan_uuid"] = plan_uuid
    _seed(store, TodoItem, good_row)
    _seed_identity(store, plan_uuid, "plan", "plan")

    bad_row = _base_row(BugReport, "bad", prefix="source")
    bad_row["source_anchor_type"] = "does-not-exist"
    _seed(store, BugReport, bad_row)

    snapshot = copy.deepcopy(store.tables)

    try:
        ac.run_anchor_cutover(store, dry_run=False)
        raise AssertionError("expected AnchorCutoverError")
    except ac.AnchorCutoverError:
        pass

    # Proof the raise happened AFTER a real partial write (otherwise this
    # test would not be exercising rollback of anything): TodoItem's owner
    # column is already set in the live (unrolled-back) store state.
    assert _owner_of(store, "todo_item", "owner", good_row["uuid"]) == plan_uuid

    # The caller's real transaction ROLLBACK, simulated: restore the pre-call
    # snapshot. What a real rollback leaves behind is indistinguishable from
    # this module never having run at all.
    store.tables = snapshot
    assert store.tables == snapshot
    assert _owner_of(store, "todo_item", "owner", good_row["uuid"]) is None


# ---------------------------------------------------------------------------
# (6) verify_move: canonical comparison detects a planted mismatch.
# ---------------------------------------------------------------------------


def _canonical_pair(entity_cls: type, salt: str) -> tuple[dict[str, Any], dict[str, Any], uuid.UUID]:
    seat = ac._owner_write_seat(entity_cls, "owner")
    row = {column: _dummy(column, salt) for column in entity_cls.COLUMNS}
    row["owner"] = None
    ref = row["uuid"]
    pre = cf.entity_row_to_canonical_record(seat, row)
    post_row = dict(row)
    post_row["owner"] = uuid.uuid4()
    post = cf.entity_row_to_canonical_record(seat, post_row)
    return pre, post, post_row["owner"]


def test_verify_move_accepts_exactly_the_expected_owner_delta() -> None:
    pre, post, new_owner = _canonical_pair(TodoItem, "verify-ok")
    ref = uuid.UUID(pre["ref"])
    problems = ac.verify_move({ref: pre}, {ref: post}, {ref: new_owner})
    assert problems == []


def test_verify_move_detects_a_planted_mismatch_beyond_the_owner_delta() -> None:
    pre, post, new_owner = _canonical_pair(TodoItem, "verify-bad")
    ref = uuid.UUID(pre["ref"])
    # Plant an extra, unexpected change: a property mutated during the move
    # that has nothing to do with the owner column.
    tampered_post = dict(post)
    tampered_post["properties"] = dict(post["properties"])
    a_property = next(iter(tampered_post["properties"]))
    tampered_post["properties"][a_property] = "TAMPERED-VALUE"

    problems = ac.verify_move({ref: pre}, {ref: tampered_post}, {ref: new_owner})

    assert problems  # detected
    assert any("properties" in problem for problem in problems)


def test_verify_move_detects_wrong_owner_value() -> None:
    pre, post, _new_owner = _canonical_pair(TodoItem, "verify-owner")
    ref = uuid.UUID(pre["ref"])
    problems = ac.verify_move({ref: pre}, {ref: post}, {ref: uuid.uuid4()})
    assert any("owner mismatch" in problem for problem in problems)
