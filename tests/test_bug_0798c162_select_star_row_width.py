"""Regression tests for bug 0798c162: bug_list broke with "too many values to
unpack (expected 34)" on live 0.1.99 after migration 0029 appended an additive
owner edge column to seven tables (bug_report got `owner_uuid`; todo_item,
wish_item, runtime_comment, calendar_entry, escalation and answer_envelope got
`owner`). The bug_report read paths used `SELECT *` and unpacked each row into
a fixed 34-element tuple, so the 35th column blew up every bug_get/bug_list;
escalation_store and answer_envelope_store used `SELECT *` with fixed
positional indexing over the row -- silently order-coupled to the schema in the
same way.

The fix pins every read in those three stores to an explicit column projection
matching exactly what the row converter consumes, making the reads immune to
future additive columns. These tests prove it two ways:

- projection pinning: the executed SQL never contains a `SELECT *` projection,
  and for bug_report it lists exactly the 34 columns of _row_to_record's
  unpack, in unpack order (a drift between projection and unpack fails here
  before it can fail live);
- additive-column simulation: fakes cannot see the real schema, so
  _SchemaAwareConn simulates a post-0029 table -- it holds the WIDER row
  (including the new owner/owner_uuid column) and serves `SELECT *` at full
  width but an explicit projection at exactly the requested columns. Reads
  through the fixed stores succeed against that wider table.
"""
from __future__ import annotations

import datetime as dt
import uuid

from plan_manager.storage.answer_envelope_store import (
    get_answer_envelope, list_answer_envelopes,
)
from plan_manager.storage.bug_report_store import get_bug, list_bugs, list_bugs_page
from plan_manager.storage.escalation_store import get_escalation, list_escalations

NOW = dt.datetime(2026, 8, 7, 12, 0, 0, tzinfo=dt.timezone.utc)

# The 34 bug_report columns _row_to_record unpacks, in unpack order (table
# order of migration 0013). Deliberately restated here as frozen truth: if the
# store's projection or unpack drifts from this list, the pinning test below
# fails instead of a live bug_list.
BUG_REPORT_COLUMNS = (
    "uuid", "title", "short_description", "detailed_description",
    "expected_behavior", "actual_behavior", "reproduction", "evidence",
    "environment", "kind", "severity", "priority_nice", "status", "reporter",
    "owner", "duplicate_of_uuid", "parent_bug_uuid", "source_anchor_type",
    "source_project_id", "source_file_path", "source_plan_uuid",
    "source_revision_uuid", "source_step_uuid", "source_step_path",
    "source_ref_id", "source_command", "source_service", "confirmed_at",
    "closed_at", "reopened_at", "created_by", "created_at", "updated_at",
    "deleted_at",
)

BUG_UUID = uuid.uuid4()

# Full post-0029 bug_report row: the 34 legacy columns PLUS the additive
# owner_uuid column migration 0029 appended (the 35th value that broke the
# fixed-width unpack on live).
BUG_REPORT_TABLE_ROW = {
    "uuid": BUG_UUID, "title": "title", "short_description": "short",
    "detailed_description": "detailed", "expected_behavior": None,
    "actual_behavior": None, "reproduction": None, "evidence": None,
    "environment": None, "kind": "functional", "severity": "major",
    "priority_nice": 0, "status": "reported", "reporter": "reporter",
    "owner": None, "duplicate_of_uuid": None, "parent_bug_uuid": None,
    "source_anchor_type": "project", "source_project_id": uuid.uuid4(),
    "source_file_path": None, "source_plan_uuid": None,
    "source_revision_uuid": None, "source_step_uuid": None,
    "source_step_path": None, "source_ref_id": None, "source_command": None,
    "source_service": None, "confirmed_at": None, "closed_at": None,
    "reopened_at": None, "created_by": "creator", "created_at": NOW,
    "updated_at": NOW, "deleted_at": None,
    "owner_uuid": uuid.uuid4(),  # additive column, migration 0029
}

ESCALATION_UUID = uuid.uuid4()

# Full post-0029 escalation row: 26 legacy columns plus the appended `owner`.
ESCALATION_TABLE_ROW = {
    "uuid": ESCALATION_UUID, "primary_anchor_type": "plan",
    "anchor_project_id": None, "anchor_file_path": None,
    "anchor_plan_uuid": uuid.uuid4(), "anchor_revision_uuid": None,
    "anchor_step_uuid": None, "anchor_step_path": None, "anchor_ref_id": None,
    "reason": "reason", "from_level": None, "to_level": None,
    "status": "open", "resolution": None, "resolved_by": None,
    "resolved_at": None, "created_by": "creator", "created_at": NOW,
    "updated_at": NOW, "deleted_at": None, "addressee_level": None,
    "addressee_role": None, "forwarded_from_uuid": None,
    "chain_root_uuid": None, "sweep_priority": None, "blocks_subtree": False,
    "owner": uuid.uuid4(),  # additive column, migration 0029
}

ENVELOPE_UUID = uuid.uuid4()

# Full post-0029 answer_envelope row: 11 legacy columns plus the appended `owner`.
ANSWER_ENVELOPE_TABLE_ROW = {
    "uuid": ENVELOPE_UUID, "kind": "result", "schema_version": 1,
    "payload": {"outcome": "ok"}, "anchor_plan_uuid": None,
    "anchor_step_uuid": None, "attempt_uuid": None, "created_by": "creator",
    "created_at": NOW, "updated_at": NOW, "deleted_at": None,
    "owner": uuid.uuid4(),  # additive column, migration 0029
}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _projection(sql: str) -> str:
    """Cut the projection out of a SELECT statement (between SELECT and FROM)."""
    upper = sql.upper()
    start = upper.index("SELECT") + len("SELECT")
    end = upper.index(" FROM ")
    return sql[start:end].strip()


class _SchemaAwareConn:
    """A fake connection simulating one post-0029 table.

    Fakes cannot see the real schema, so the additive column is simulated
    here: `table_row` maps every column (INCLUDING the 0029 owner edge) to a
    value. A `SELECT *` is served at the table's full post-0029 width --
    reproducing the row shape that broke the fixed 34-tuple unpack live --
    while an explicit projection is served with exactly the requested columns,
    in the requested order. Non-SELECT statements are absorbed.
    """

    def __init__(self, table_row: dict[str, object], row_count: int = 1):
        self.table_row = table_row
        self.row_count = row_count
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql, params=None):
        sql_text = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        self.calls.append((sql_text, list(params or [])))
        if not sql_text.lstrip().upper().startswith("SELECT"):
            return _Result([])
        projection = _projection(sql_text)
        if projection.replace(" ", "").lower() == "count(*)":
            return _Result([(self.row_count,)])
        values: list[object] = []
        for term in projection.split(","):
            term = term.strip()
            if term == "*":
                values.extend(self.table_row.values())
            elif term.lower().startswith("count(*) over()"):
                values.append(self.row_count)
            else:
                values.append(self.table_row[term])
        return _Result([tuple(values)] * self.row_count)


# --- projection pinning ------------------------------------------------------


def test_bug_report_reads_project_explicit_columns_in_unpack_order() -> None:
    conn = _SchemaAwareConn(BUG_REPORT_TABLE_ROW)
    get_bug(conn, BUG_UUID)
    list_bugs(conn)
    list_bugs_page(conn)
    assert len(conn.calls) == 3
    for sql_text, _params in conn.calls:
        projection = _projection(sql_text)
        assert "*" not in projection.replace("count(*) OVER() AS total", ""), (
            "bug_report reads must never SELECT * (bug 0798c162)"
        )
        named = [
            term.strip() for term in projection.split(",")
            if not term.strip().lower().startswith("count(*) over()")
        ]
        assert tuple(named) == BUG_REPORT_COLUMNS, (
            "bug_report projection must list exactly _row_to_record's 34 "
            "columns in unpack order"
        )


def test_escalation_and_envelope_reads_never_select_star() -> None:
    esc_conn = _SchemaAwareConn(ESCALATION_TABLE_ROW)
    get_escalation(esc_conn, ESCALATION_UUID)
    list_escalations(esc_conn)
    env_conn = _SchemaAwareConn(ANSWER_ENVELOPE_TABLE_ROW)
    get_answer_envelope(env_conn, ENVELOPE_UUID)
    list_answer_envelopes(env_conn)
    for sql_text, _params in esc_conn.calls + env_conn.calls:
        assert "*" not in _projection(sql_text), (
            "0029-swept reads must use an explicit projection, not SELECT *"
        )


# --- additive-column immunity ------------------------------------------------


def test_bug_get_and_lists_tolerate_additive_owner_uuid_column() -> None:
    conn = _SchemaAwareConn(BUG_REPORT_TABLE_ROW, row_count=2)

    record = get_bug(conn, BUG_UUID)
    assert record is not None
    assert record.bug_uuid == BUG_UUID
    assert record.status == "reported"

    records = list_bugs(conn)
    assert len(records) == 2
    assert records[0].title == "title"

    page, total = list_bugs_page(conn, limit=10, offset=0)
    assert total == 2
    assert len(page) == 2
    assert page[0].reporter == "reporter"
    assert page[0].created_at == NOW.isoformat()


def test_escalation_reads_tolerate_additive_owner_column() -> None:
    conn = _SchemaAwareConn(ESCALATION_TABLE_ROW, row_count=1)

    record = get_escalation(conn, ESCALATION_UUID)
    assert record is not None
    assert record.escalation_uuid == ESCALATION_UUID
    assert record.status == "open"
    assert record.blocks_subtree is False

    records = list_escalations(conn)
    assert len(records) == 1
    assert records[0].reason == "reason"
    assert records[0].anchor_plan_uuid == ESCALATION_TABLE_ROW["anchor_plan_uuid"]


def test_answer_envelope_reads_tolerate_additive_owner_column() -> None:
    conn = _SchemaAwareConn(ANSWER_ENVELOPE_TABLE_ROW, row_count=1)

    record = get_answer_envelope(conn, ENVELOPE_UUID)
    assert record is not None
    assert record.envelope_uuid == ENVELOPE_UUID
    assert record.payload == {"outcome": "ok"}

    records = list_answer_envelopes(conn)
    assert len(records) == 1
    assert records[0].kind == "result"
    assert records[0].created_at == NOW.isoformat()
