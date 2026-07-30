"""Bug 4375c341: todo_queue died sorting a datetime against ISO strings.

`bug_fix_store._row_to_record` inverted its `isinstance(..., str)` guard for
created_at/updated_at on the dict (crud_*) path: it called `.isoformat()` exactly
when the value was ALREADY a string and passed it through unchanged when it was a
`datetime`. psycopg returns `timestamptz` as a `datetime`, so a live row put a
`datetime` into `BugFix.created_at` — a field annotated `str`. From there
`work_item_from_bug_fix` copied it into `WorkItem.created_at`, and
`order_queue`'s sort compared that `datetime` against the ISO strings every
other work source produces:

    -32603 "'<' not supported between instances of 'str' and 'datetime.datetime'"

Reproduced live on 192.168.254.26 at 0.1.88 (261 passed, 1 failed, 121 skipped),
against a 0.1.87 baseline of 530/0/119.

These tests use real `datetime` objects deliberately. The pre-existing suites
missed this because their fake cursors hand back strings, for which the inverted
branch never reaches the ordering path where the mixed comparison happens.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from plan_manager.domain.bug_fix import BugFix
from plan_manager.runtime.work_item import ResourceAvailability, WorkKind
from plan_manager.runtime.work_ordering import order_queue
from plan_manager.runtime.work_sources import work_item_from_bug_fix
from plan_manager.storage.bug_fix_store import _row_to_record

_NOW = datetime(2026, 7, 30, 10, 22, 44, tzinfo=timezone.utc)

# Every timestamp column of bug_fix, so the mapper is exercised whole rather than
# only on the two columns that were wrong.
_TIMESTAMP_COLUMNS = (
    "started_at",
    "implemented_at",
    "verified_at",
    "created_at",
    "updated_at",
    "deleted_at",
)


def _row(**overrides: Any) -> dict[str, Any]:
    """A bug_fix row as psycopg really returns it: timestamps are datetimes."""
    row: dict[str, Any] = {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "bug_uuid": "22222222-2222-2222-2222-222222222222",
        "status": "implemented",
        "fix_type": "code",
        "summary": "s",
        "implementation_notes": None,
        "source_project_id": None,
        "branch": None,
        "commit_hash": None,
        "pull_request": None,
        "changed_files": None,
        "tests": None,
        "author": "a",
        "reviewer": None,
        "started_at": _NOW,
        "implemented_at": _NOW,
        "verified_at": None,
        "verification_method": None,
        "expected_result": None,
        "actual_result": None,
        "passed": None,
        "revert_info": None,
        "created_by": "a",
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("column", _TIMESTAMP_COLUMNS)
def test_every_timestamp_column_becomes_an_iso_string(column: str) -> None:
    """No timestamp may reach the domain object as a datetime.

    BugFix annotates each of these as `str`. A datetime here does not fail at the
    boundary; it fails much later, wherever the value is compared or serialized.
    """
    record = _row_to_record(_row(**{column: _NOW}))
    value = getattr(record, column)
    assert isinstance(value, str), (
        f"BugFix.{column} is a {type(value).__name__}, not the ISO string its "
        "annotation promises"
    )
    assert value == _NOW.isoformat()


def test_a_null_timestamp_stays_none() -> None:
    """The conversion must not turn an absent timestamp into a string."""
    record = _row_to_record(_row(verified_at=None, deleted_at=None))
    assert record.verified_at is None
    assert record.deleted_at is None


def test_an_already_string_timestamp_is_passed_through() -> None:
    """Idempotent: a row that already carries ISO strings is not mangled.

    This is the case the inverted guard was presumably reaching for. It must hold
    without breaking the datetime case.
    """
    iso = _NOW.isoformat()
    record = _row_to_record(_row(created_at=iso, updated_at=iso))
    assert record.created_at == iso
    assert record.updated_at == iso


def test_order_queue_sorts_a_bug_fix_beside_other_sources() -> None:
    """The live failure path: one datetime among ISO strings breaks the sort.

    order_key puts created_at in the sort tuple, so a single work source leaking a
    datetime makes sorted() compare it against every other source's ISO string.
    """
    fix = _row_to_record(_row(created_at=_NOW, updated_at=_NOW))
    from_fix = work_item_from_bug_fix(fix)
    # A second item standing in for any other work source, which all yield ISO.
    other = dataclasses.replace(
        from_fix,
        work_kind=WorkKind.TODO.value,
        source_uuid="33333333-3333-3333-3333-333333333333",
        created_at=(_NOW - timedelta(days=1)).isoformat(),
    )

    ordered = order_queue([from_fix, other], ResourceAvailability())

    assert len(ordered) == 2
    # Oldest first, and both keys comparable.
    assert ordered[0].created_at == (_NOW - timedelta(days=1)).isoformat()
    assert isinstance(ordered[1].created_at, str)


def test_work_item_created_at_is_a_string() -> None:
    """The value crossing into the queue must already be a string."""
    item = work_item_from_bug_fix(_row_to_record(_row()))
    assert isinstance(item.created_at, str), (
        f"WorkItem.created_at is a {type(item.created_at).__name__}; order_key "
        "compares this field against other sources' ISO strings"
    )


def test_no_bug_fix_timestamp_field_is_left_unconverted() -> None:
    """Sweep the whole record: no field may hold a datetime.

    Guards against the same defect reappearing on a column this test file does
    not name individually.
    """
    record = _row_to_record(_row(verified_at=_NOW, deleted_at=_NOW))
    offenders = [
        field.name
        for field in dataclasses.fields(BugFix)
        if isinstance(getattr(record, field.name), datetime)
    ]
    assert offenders == [], f"fields still holding a datetime: {offenders}"
