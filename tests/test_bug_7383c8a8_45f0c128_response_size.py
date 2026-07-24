"""Regression tests for bugs 7383c8a8 and 45f0c128 (project f06b7269-cc9c-4293-886b-24984e4033ba):

- 7383c8a8 (minor): bug_list response oversized -- full bug bodies embedded, no
  usable pagination. Live measurement: bug_list(active_only=true) returned
  176,477 chars for 42 active bugs (135,279 chars for 27 bugs, measured
  earlier the same day).
- 45f0c128 (minor): project_view response oversized despite todo/bug limit
  params -- it embedded the full detailed_description of every bug row
  (63,439 chars spilled for just 7 bugs).

Root cause (shared): both commands always inlined the complete BugReport
record (detailed_description, expected_behavior, actual_behavior,
reproduction, evidence, environment) in every row, with no caller-selectable
compact shape and, for bug_list, no bounded default.

Fix:
- BugReport.SUMMARY_FIELDS widened (plan_manager/domain/bug_report.py) to a
  bounded, triage-useful projection: uuid, bug_uuid, title,
  short_description, status, kind, severity, priority_nice, reporter, owner,
  source_anchor_type, source_project_id, source_plan_uuid, source_command,
  source_service, created_at, updated_at, closed_at -- still excluding the
  free-text bodies.
- bug_list's `view` parameter now defaults to "summary" (plan_manager/
  commands/bug_list_command.py), so a caller doing nothing differently gets
  the bounded shape; limit/offset/total pagination (default 50, max 200) was
  already present and unchanged; `view=full` and bug_get still return the
  complete record.
- project_view's todo/bug rows are now ALWAYS the summary projection
  (plan_manager/commands/project_view_command.py calls
  r.to_summary_payload() instead of r.to_payload()) -- there is no view
  param on project_view, so this is unconditional; full detail remains one
  bug_get/todo_get call away.

This suite is purely static/in-process (no live database, no live server),
mirroring tests/test_bug_8a13977d_list_view_projection.py's and
tests/test_project_view_command.py's own conventions: dataclass entities
built directly with a multi-KB detailed_description/description, monkeypatch
over the command modules' imported store functions, direct
asyncio.run(Command().execute(**kwargs)) against the real production code
path -- no mocked projection logic.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager

from plan_manager.commands import bug_list_command, project_view_command
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.todo import TodoItem

BUG_UUID = uuid.uuid4()
TODO_UUID = uuid.uuid4()
PROJECT_UUID = uuid.uuid4()
PLAN_UUID = uuid.uuid4()

# The exact shape that spilled live: a multi-KB free-text body.
_BIG_BODY = "lorem ipsum dolor sit amet " * 300  # ~8.1 KB


@contextmanager
def _fake_db():
    yield object()


def _big_bug(**overrides) -> BugReport:
    fields = dict(
        bug_uuid=BUG_UUID,
        title="Oversized response bug",
        short_description="bug_list/project_view embed full bug bodies",
        detailed_description=_BIG_BODY,
        expected_behavior=_BIG_BODY,
        actual_behavior=_BIG_BODY,
        reproduction=_BIG_BODY,
        evidence={"raw": _BIG_BODY},
        environment=_BIG_BODY,
        kind="performance",
        severity="minor",
        priority_nice=0,
        status="reported",
        reporter="tester",
        owner=None,
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type="project",
        source_project_id=PROJECT_UUID,
        source_file_path=None,
        source_plan_uuid=None,
        source_revision_uuid=None,
        source_step_uuid=None,
        source_step_path=None,
        source_ref_id=None,
        source_command=None,
        source_service=None,
        confirmed_at=None,
        closed_at=None,
        reopened_at=None,
        created_by="tester",
        created_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
        deleted_at=None,
    )
    fields.update(overrides)
    return BugReport(**fields)


def _big_todo(**overrides) -> TodoItem:
    fields = dict(
        todo_uuid=TODO_UUID,
        title="Oversized todo",
        description=_BIG_BODY,
        kind="task",
        status="open",
        priority_nice=0,
        created_by="tester",
        assigned_to=None,
        created_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
        started_at=None,
        resolved_at=None,
        due_at=None,
        primary_anchor_type="project",
        anchor_project_id=PROJECT_UUID,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        blocking_reason=_BIG_BODY,
        execution_result=_BIG_BODY,
        deleted_at=None,
    )
    fields.update(overrides)
    return TodoItem(**fields)


# --- bug 7383c8a8: bug_list -------------------------------------------------


BODY_FIELDS = (
    "detailed_description", "expected_behavior", "actual_behavior",
    "reproduction", "evidence", "environment",
)


def _run_bug_list(monkeypatch, bugs, total, **kwargs):
    def fake_list_bugs_page(conn, **_kwargs):
        return bugs, total

    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_list_command, "list_bugs_page", fake_list_bugs_page)
    result = asyncio.run(bug_list_command.BugListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_bug_list_default_omits_view_does_not_leak_body(monkeypatch) -> None:
    """The characterizing case: a caller that does nothing differently (no
    `view` param, same as every pre-fix caller) must NOT get the bug's
    multi-KB body back."""
    data = _run_bug_list(monkeypatch, [_big_bug()], 1)
    assert len(data["bugs"]) == 1
    row = data["bugs"][0]
    for field in BODY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default bug_list row: {sorted(row)}"
    assert row["uuid"] == str(BUG_UUID)
    assert row["short_description"] == "bug_list/project_view embed full bug bodies"


def test_bug_list_default_response_bounded_in_bytes(monkeypatch) -> None:
    """Direct reproduction of the live measurement's shape: a page of bugs
    with realistic multi-KB bodies must serialize far under what the
    pre-fix (always-full) shape would have produced."""
    bugs = [_big_bug(bug_uuid=uuid.uuid4()) for _ in range(10)]
    data = _run_bug_list(monkeypatch, bugs, 10)
    size = len(json.dumps(data).encode("utf-8"))
    # Each _BIG_BODY is ~8.1 KB and six such fields exist per bug; the
    # pre-fix shape would have been well over 400 KB for 10 rows. The fixed
    # shape (summary rows only) must stay under 10 KB.
    assert size < 10_000, f"bug_list default response is {size} bytes for 10 rows -- still unbounded"


def test_bug_list_pagination_fields_present_and_bounded(monkeypatch) -> None:
    """(b) explicit limit/offset paging with a bounded default, plus total."""
    data = _run_bug_list(monkeypatch, [_big_bug()], 42)
    assert data["total"] == 42
    assert data["limit"] == 50  # documented default
    assert data["offset"] == 0


def test_bug_list_limit_above_max_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_list_command, "list_bugs_page", lambda conn, **kw: ([], 0))
    result = asyncio.run(bug_list_command.BugListCommand().execute(limit=201))
    payload = result.to_dict()
    assert "error" in payload
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_bug_list_view_full_still_returns_complete_body(monkeypatch) -> None:
    """(c) full bodies remain available -- via view=full here, and via
    bug_get regardless."""
    data = _run_bug_list(monkeypatch, [_big_bug()], 1, view="full")
    row = data["bugs"][0]
    for field in BODY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full bug_list row"
    assert row["detailed_description"] == _BIG_BODY


def test_bug_list_view_summary_explicit_matches_default(monkeypatch) -> None:
    default_data = _run_bug_list(monkeypatch, [_big_bug()], 1)
    explicit_data = _run_bug_list(monkeypatch, [_big_bug()], 1, view="summary")
    assert default_data["bugs"] == explicit_data["bugs"]


# --- bug 45f0c128: project_view ---------------------------------------------


def _run_project_view(monkeypatch, todos, bugs, **kwargs):
    def fake_todos_page(conn, *, limit, offset, **_kwargs):
        page = todos[offset:offset + limit]
        return page, len(todos)

    def fake_bugs_page(conn, *, limit, offset, **_kwargs):
        page = bugs[offset:offset + limit]
        return page, len(bugs)

    def fake_comments_page(conn, *, limit, offset, **_kwargs):
        return [], 0

    monkeypatch.setattr(project_view_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_view_command, "list_todos_page", fake_todos_page)
    monkeypatch.setattr(project_view_command, "list_bugs_page", fake_bugs_page)
    monkeypatch.setattr(project_view_command, "list_comments_page", fake_comments_page)
    result = asyncio.run(project_view_command.ProjectViewCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_project_view_bug_rows_do_not_leak_body(monkeypatch) -> None:
    data = _run_project_view(monkeypatch, [], [_big_bug()], project=str(PROJECT_UUID))
    assert len(data["bugs"]) == 1
    row = data["bugs"][0]
    for field in BODY_FIELDS:
        assert field not in row, f"{field!r} leaked into project_view's bug row: {sorted(row)}"
    assert row["uuid"] == str(BUG_UUID)
    assert row["match_source"] == "direct"


def test_project_view_todo_rows_do_not_leak_body(monkeypatch) -> None:
    """Task's explicit instruction: check todo rows for the SAME defect."""
    data = _run_project_view(monkeypatch, [_big_todo()], [], project=str(PROJECT_UUID))
    assert len(data["todos"]) == 1
    row = data["todos"][0]
    for field in ("description", "blocking_reason", "execution_result"):
        assert field not in row, f"{field!r} leaked into project_view's todo row: {sorted(row)}"
    assert row["uuid"] == str(TODO_UUID)


def test_project_view_response_bounded_in_bytes_despite_limit_params(monkeypatch) -> None:
    """Direct reproduction of the live measurement's shape: limit params
    were already honored (row COUNT was bounded) but each row was still the
    full record. Confirms the fix bounds BYTES, not just row count."""
    bugs = [_big_bug(bug_uuid=uuid.uuid4()) for _ in range(7)]
    data = _run_project_view(monkeypatch, [], bugs, project=str(PROJECT_UUID), bug_limit=7)
    size = len(json.dumps(data).encode("utf-8"))
    assert size < 10_000, f"project_view response is {size} bytes for 7 bug rows -- still unbounded"


def test_project_view_honors_existing_limit_params_unchanged(monkeypatch) -> None:
    many_bugs = [_big_bug(bug_uuid=uuid.uuid4()) for _ in range(5)]
    data = _run_project_view(monkeypatch, [], many_bugs, project=str(PROJECT_UUID), bug_limit=2, bug_offset=1)
    assert len(data["bugs"]) == 2
    assert data["bug_total"] == 5
    assert data["bug_limit"] == 2
    assert data["bug_offset"] == 1
