"""Regression tests for todo f47a2db0 (project f06b7269-cc9c-4293-886b-24984e4033ba):

todo_queue surfaced only the GLOBAL TODO-derived queue, with no way to scope it to a
single plan or project -- every caller had to fetch everything and filter client-side.

Fix:
- plan_manager/runtime/work_item.py: WorkItem gains `project_uuid: uuid.UUID | None`.
- plan_manager/runtime/work_sources.py: work_item_from_todo/_bug_report/_escalation
  populate project_uuid directly from the source record's own project field
  (todo.anchor_project_id / bug.source_project_id / escalation.anchor_project_id).
- plan_manager/runtime/work_queue.py: build_unified_queue fills project_uuid, for any
  item that carries a plan_uuid but no direct project of its own, from that plan's
  primary_project_id (one batched query, never N+1); an item anchored to neither a
  project nor a plan with a primary_project_id keeps project_uuid=None and simply never
  matches a `project` filter.
- plan_manager/commands/todo_queue_command.py: new `anchor_plan` (name-or-UUID, resolved
  via resolve_plan like todo_list's sibling filter) and `project` (UUID, INVALID_FILTER
  on malformed input) parameters, applied after the todo_kind filter and before
  pagination, composing with each other and the existing availability/lock filters.

This suite follows this repo's established style for command/queue-layer tests (see
tests/test_runtime_filtering.py, tests/test_runtime_list_filters.py,
tests/test_bug_7383c8a8_45f0c128_response_size.py): pure unit tests, monkeypatched
db_connection / store functions / fake psycopg-shaped connections -- no real Postgres.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import todo_queue_command
from plan_manager.commands.todo_queue_command import TodoQueueCommand
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.todo import TodoItem
from plan_manager.runtime import work_queue as wq
from plan_manager.runtime.work_item import ResourceAvailability, WorkItem, WorkKind
from plan_manager.runtime.work_queue import build_unified_queue
from plan_manager.runtime.work_sources import (
    work_item_from_bug_report,
    work_item_from_escalation,
    work_item_from_todo,
)


# --- fixture builders --------------------------------------------------------------


def _todo(**overrides) -> TodoItem:
    fields = dict(
        todo_uuid=uuid.uuid4(),
        title="t",
        description="d",
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
        primary_anchor_type="none",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        blocking_reason=None,
        execution_result=None,
        deleted_at=None,
    )
    fields.update(overrides)
    return TodoItem(**fields)


def _bug(**overrides) -> BugReport:
    fields = dict(
        bug_uuid=uuid.uuid4(),
        title="b",
        short_description="s",
        detailed_description="d",
        expected_behavior="e",
        actual_behavior="a",
        reproduction="r",
        evidence=None,
        environment="env",
        kind="functional",
        severity="minor",
        priority_nice=0,
        status="confirmed",
        reporter="tester",
        owner=None,
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type="none",
        source_project_id=None,
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


def _escalation(**overrides) -> Escalation:
    fields = dict(
        escalation_uuid=uuid.uuid4(),
        primary_anchor_type="none",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        reason="r",
        from_level=None,
        to_level=None,
        status="open",
        resolution=None,
        resolved_by=None,
        resolved_at=None,
        created_by="tester",
        created_at="2026-07-24T00:00:00+00:00",
        updated_at="2026-07-24T00:00:00+00:00",
        deleted_at=None,
        addressee_level=None,
        addressee_role=None,
        forwarded_from_uuid=None,
        chain_root_uuid=None,
        sweep_priority=None,
        blocks_subtree=False,
    )
    fields.update(overrides)
    return Escalation(**fields)


def _work_item(*, work_kind=WorkKind.TODO.value, plan_uuid=None, project_uuid=None, source_uuid=None) -> WorkItem:
    return WorkItem(
        work_kind=work_kind,
        source_uuid=source_uuid or uuid.uuid4(),
        title="item",
        priority_nice=0,
        ready=True,
        requires_runtime=False,
        plan_uuid=plan_uuid,
        project_uuid=project_uuid,
    )


@contextmanager
def _fake_db():
    yield object()


# --- WorkItem / payload ------------------------------------------------------------


def test_work_item_project_uuid_defaults_none() -> None:
    item = _work_item()
    assert item.project_uuid is None


def test_work_item_to_payload_includes_project_uuid() -> None:
    project_uuid = uuid.uuid4()
    item = _work_item(project_uuid=project_uuid)
    payload = item.to_payload()
    assert payload["project_uuid"] == str(project_uuid)


def test_work_item_to_payload_project_uuid_none_stays_none() -> None:
    item = _work_item(project_uuid=None)
    assert item.to_payload()["project_uuid"] is None


# --- work_sources: direct project population ---------------------------------------


def test_work_item_from_todo_populates_project_uuid_from_anchor() -> None:
    project_uuid = uuid.uuid4()
    todo = _todo(anchor_project_id=project_uuid)
    item = work_item_from_todo(todo)
    assert item.project_uuid == project_uuid


def test_work_item_from_todo_project_uuid_none_when_unset() -> None:
    todo = _todo(anchor_project_id=None)
    item = work_item_from_todo(todo)
    assert item.project_uuid is None


def test_work_item_from_bug_report_populates_project_uuid_from_source() -> None:
    project_uuid = uuid.uuid4()
    bug = _bug(source_project_id=project_uuid)
    item = work_item_from_bug_report(bug)
    assert item.project_uuid == project_uuid


def test_work_item_from_escalation_populates_project_uuid_from_anchor() -> None:
    project_uuid = uuid.uuid4()
    esc = _escalation(anchor_project_id=project_uuid)
    item = work_item_from_escalation(esc)
    assert item.project_uuid == project_uuid


# --- work_queue: plan-level fallback -------------------------------------------------


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakePlanConn:
    """Answers exactly the one batched plan-project lookup query."""

    def __init__(self, plan_projects: dict[uuid.UUID, uuid.UUID | None]) -> None:
        self._plan_projects = plan_projects
        self.queries: list[tuple] = []

    def execute(self, sql: str, params: tuple) -> _FakeCursor:
        assert "primary_project_id" in sql
        self.queries.append(params)
        (requested_uuids,) = params
        rows = [(pu, self._plan_projects.get(pu)) for pu in requested_uuids]
        return _FakeCursor(rows)


def test_plan_primary_projects_batches_a_single_query() -> None:
    plan_a, plan_b = uuid.uuid4(), uuid.uuid4()
    project_a = uuid.uuid4()
    conn = _FakePlanConn({plan_a: project_a, plan_b: None})

    result = wq._plan_primary_projects(conn, {plan_a, plan_b})

    assert result == {plan_a: project_a, plan_b: None}
    assert len(conn.queries) == 1


def test_plan_primary_projects_empty_input_short_circuits_no_query() -> None:
    conn = _FakePlanConn({})
    result = wq._plan_primary_projects(conn, set())
    assert result == {}
    assert conn.queries == []


def test_fill_project_uuid_from_plan_applies_fallback_when_item_has_no_direct_project() -> None:
    plan_uuid = uuid.uuid4()
    project_uuid = uuid.uuid4()
    conn = _FakePlanConn({plan_uuid: project_uuid})
    item = _work_item(work_kind=WorkKind.PROPAGATION.value, plan_uuid=plan_uuid, project_uuid=None)

    filled = wq._fill_project_uuid_from_plan(conn, [item])

    assert filled[0].project_uuid == project_uuid


def test_fill_project_uuid_from_plan_leaves_direct_project_untouched() -> None:
    plan_uuid = uuid.uuid4()
    own_project = uuid.uuid4()
    plan_project = uuid.uuid4()
    conn = _FakePlanConn({plan_uuid: plan_project})
    item = _work_item(work_kind=WorkKind.TODO.value, plan_uuid=plan_uuid, project_uuid=own_project)

    filled = wq._fill_project_uuid_from_plan(conn, [item])

    assert filled[0].project_uuid == own_project


def test_fill_project_uuid_from_plan_no_plan_uuid_stays_none() -> None:
    conn = _FakePlanConn({})
    item = _work_item(work_kind=WorkKind.BUG_FIX.value, plan_uuid=None, project_uuid=None)

    filled = wq._fill_project_uuid_from_plan(conn, [item])

    assert filled[0].project_uuid is None
    assert conn.queries == []


def test_fill_project_uuid_from_plan_plan_without_primary_project_stays_none() -> None:
    plan_uuid = uuid.uuid4()
    conn = _FakePlanConn({plan_uuid: None})
    item = _work_item(work_kind=WorkKind.VERIFICATION.value, plan_uuid=plan_uuid, project_uuid=None)

    filled = wq._fill_project_uuid_from_plan(conn, [item])

    assert filled[0].project_uuid is None


def test_fill_project_uuid_from_plan_deduplicates_plan_lookups() -> None:
    plan_uuid = uuid.uuid4()
    project_uuid = uuid.uuid4()
    conn = _FakePlanConn({plan_uuid: project_uuid})
    items = [
        _work_item(work_kind=WorkKind.PROPAGATION.value, plan_uuid=plan_uuid, project_uuid=None),
        _work_item(work_kind=WorkKind.VERIFICATION.value, plan_uuid=plan_uuid, project_uuid=None),
    ]

    filled = wq._fill_project_uuid_from_plan(conn, items)

    assert all(it.project_uuid == project_uuid for it in filled)
    assert len(conn.queries) == 1
    assert len(conn.queries[0][0]) == 1  # one distinct plan_uuid requested, not two


# --- build_unified_queue: end-to-end plan fallback ----------------------------------


@contextmanager
def _patched_sources_with_records(*, todos, bugs=(), escalations=()):
    from unittest.mock import patch
    import contextlib as _contextlib

    with _contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(wq, "list_todos", lambda conn, **k: list(todos)))
        stack.enter_context(patch.object(wq, "list_bugs", lambda conn, **k: list(bugs)))
        stack.enter_context(patch.object(wq, "list_bug_fixes", lambda conn, **k: []))
        stack.enter_context(patch.object(wq, "list_bug_fix_propagations", lambda conn, **k: []))
        stack.enter_context(patch.object(wq, "list_execution_attempts", lambda conn, **k: []))
        stack.enter_context(patch.object(wq, "list_review_results", lambda conn, **k: []))
        stack.enter_context(patch.object(wq, "list_escalations", lambda conn, **k: list(escalations)))
        yield stack


def test_build_unified_queue_fills_todo_project_uuid_via_plan_fallback() -> None:
    plan_uuid = uuid.uuid4()
    plan_project = uuid.uuid4()
    todo = _todo(status="open", anchor_project_id=None, anchor_plan_uuid=plan_uuid)
    conn = _FakePlanConn({plan_uuid: plan_project})

    with _patched_sources_with_records(todos=[todo]):
        items = build_unified_queue(conn, as_ready=[], availability=ResourceAvailability())

    todo_items = [it for it in items if it.work_kind == WorkKind.TODO.value]
    assert len(todo_items) == 1
    assert todo_items[0].project_uuid == plan_project


def test_build_unified_queue_direct_project_wins_over_plan_fallback() -> None:
    plan_uuid = uuid.uuid4()
    own_project = uuid.uuid4()
    plan_project = uuid.uuid4()
    todo = _todo(status="open", anchor_project_id=own_project, anchor_plan_uuid=plan_uuid)
    conn = _FakePlanConn({plan_uuid: plan_project})

    with _patched_sources_with_records(todos=[todo]):
        items = build_unified_queue(conn, as_ready=[], availability=ResourceAvailability())

    todo_items = [it for it in items if it.work_kind == WorkKind.TODO.value]
    assert todo_items[0].project_uuid == own_project


# --- TodoQueueCommand: anchor_plan / project filters --------------------------------


class _DummyPlan:
    def __init__(self, plan_uuid: uuid.UUID) -> None:
        self.uuid = plan_uuid


def _run_queue(monkeypatch, items, resolve_plan_uuid=None, **kwargs):
    monkeypatch.setattr(todo_queue_command, "db_connection", _fake_db)
    monkeypatch.setattr(todo_queue_command, "build_unified_queue", lambda conn, as_ready, availability: items)
    if resolve_plan_uuid is not None:
        monkeypatch.setattr(todo_queue_command, "resolve_plan", lambda conn, plan: _DummyPlan(resolve_plan_uuid))
    result = asyncio.run(TodoQueueCommand().execute(**kwargs))
    return result


def _fixture_queue():
    """Two plans, two projects, one unanchored todo, plus a non-todo item that must
    never leak into totals/results regardless of filters."""
    plan_a, plan_b = uuid.uuid4(), uuid.uuid4()
    project_x, project_y = uuid.uuid4(), uuid.uuid4()
    items = [
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=plan_a, project_uuid=project_x),
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=plan_a, project_uuid=project_y),
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=plan_b, project_uuid=project_x),
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=None, project_uuid=None),
        _work_item(work_kind=WorkKind.BUG_INVESTIGATION.value, plan_uuid=plan_a, project_uuid=project_x),
    ]
    return items, plan_a, plan_b, project_x, project_y


def test_todo_queue_unfiltered_total_excludes_non_todo_kinds(monkeypatch) -> None:
    items, *_ = _fixture_queue()
    result = _run_queue(monkeypatch, items)
    data = result.to_dict()["data"]
    assert data["total"] == 4  # 4 todo items; the bug_investigation item is excluded


def test_todo_queue_anchor_plan_filters_to_matching_plan(monkeypatch) -> None:
    items, plan_a, plan_b, project_x, project_y = _fixture_queue()
    result = _run_queue(monkeypatch, items, resolve_plan_uuid=plan_a, anchor_plan="plan-a")
    data = result.to_dict()["data"]
    assert data["total"] == 2
    assert all(row["plan_uuid"] == str(plan_a) for row in data["queue"])


def test_todo_queue_project_filters_to_matching_project(monkeypatch) -> None:
    items, plan_a, plan_b, project_x, project_y = _fixture_queue()
    result = _run_queue(monkeypatch, items, project=str(project_x))
    data = result.to_dict()["data"]
    assert data["total"] == 2
    assert all(row["project_uuid"] == str(project_x) for row in data["queue"])


def test_todo_queue_combined_anchor_plan_and_project_filters_compose(monkeypatch) -> None:
    items, plan_a, plan_b, project_x, project_y = _fixture_queue()
    result = _run_queue(
        monkeypatch, items, resolve_plan_uuid=plan_a, anchor_plan="plan-a", project=str(project_x),
    )
    data = result.to_dict()["data"]
    assert data["total"] == 1
    assert data["queue"][0]["plan_uuid"] == str(plan_a)
    assert data["queue"][0]["project_uuid"] == str(project_x)


def test_todo_queue_project_filter_excludes_unanchored_items(monkeypatch) -> None:
    items, plan_a, plan_b, project_x, project_y = _fixture_queue()
    result = _run_queue(monkeypatch, items, project=str(project_y))
    data = result.to_dict()["data"]
    assert data["total"] == 1
    assert data["queue"][0]["project_uuid"] == str(project_y)


def test_todo_queue_malformed_project_uuid_raises_invalid_filter(monkeypatch) -> None:
    items, *_ = _fixture_queue()
    result = _run_queue(monkeypatch, items, project="not-a-uuid")
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == "INVALID_FILTER"


def test_todo_queue_pagination_math_after_filtering(monkeypatch) -> None:
    """Filtering happens before pagination: total reflects the filtered count, and
    limit/offset slice the filtered (not the unfiltered) sequence."""
    plan_a = uuid.uuid4()
    project_x = uuid.uuid4()
    matching = [
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=plan_a, project_uuid=project_x)
        for _ in range(5)
    ]
    non_matching = [
        _work_item(work_kind=WorkKind.TODO.value, plan_uuid=uuid.uuid4(), project_uuid=uuid.uuid4())
        for _ in range(10)
    ]
    items = matching + non_matching

    result = _run_queue(monkeypatch, items, project=str(project_x), limit=2, offset=1)
    data = result.to_dict()["data"]

    assert data["total"] == 5
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert len(data["queue"]) == 2
    assert all(row["project_uuid"] == str(project_x) for row in data["queue"])


def test_todo_queue_total_never_exceeds_unfiltered_total(monkeypatch) -> None:
    items, plan_a, plan_b, project_x, project_y = _fixture_queue()
    unfiltered = _run_queue(monkeypatch, items).to_dict()["data"]["total"]
    filtered = _run_queue(monkeypatch, items, project=str(project_x)).to_dict()["data"]["total"]
    assert filtered <= unfiltered
