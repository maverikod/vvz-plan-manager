"""Runtime listing pagination/filters plus unified work-queue ordering test coverage (C-035, C-027, HRS {d118} bullet 23)."""

import contextlib
import types
import uuid
from unittest.mock import patch

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.runtime_filtering import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    Pagination,
    RuntimeFilters,
    parse_filters,
    parse_pagination,
)
from plan_manager.runtime.work_item import WorkItem, ResourceAvailability, WorkKind
from plan_manager.runtime.work_ordering import order_queue, pause_dependent_as
from plan_manager.runtime import work_queue as wq
from plan_manager.runtime.work_queue import build_unified_queue


def test_parse_pagination_defaults() -> None:
    pagination = parse_pagination({})
    assert pagination == Pagination(limit=DEFAULT_LIMIT, offset=0)


def test_parse_pagination_explicit_values() -> None:
    pagination = parse_pagination({"limit": 10, "offset": 5})
    assert pagination == Pagination(limit=10, offset=5)


def test_parse_pagination_clamps_limit_to_max() -> None:
    pagination = parse_pagination({"limit": 500})
    assert pagination == Pagination(limit=MAX_LIMIT, offset=0)


def test_parse_pagination_rejects_limit_below_one() -> None:
    try:
        parse_pagination({"limit": 0})
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_PAGINATION"


def test_parse_pagination_rejects_negative_offset() -> None:
    try:
        parse_pagination({"offset": -1})
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_PAGINATION"


def test_parse_pagination_rejects_non_integer_limit() -> None:
    try:
        parse_pagination({"limit": "ten"})
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_PAGINATION"


def test_parse_pagination_rejects_non_integer_offset() -> None:
    try:
        parse_pagination({"offset": "five"})
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_PAGINATION"


def test_parse_filters_empty_params_yields_empty_values() -> None:
    filters = parse_filters({}, ["status"])
    assert filters.values == {}
    assert filters.get("status") is None
    assert filters.get("status", "fallback") == "fallback"


def test_parse_filters_accepts_valid_string_and_integer_fields() -> None:
    filters = parse_filters({"status": "open", "priority": 5}, ["status", "priority"])
    assert filters.values == {"status": "open", "priority": 5}


def test_parse_filters_rejects_priority_out_of_range() -> None:
    try:
        parse_filters({"priority": 100}, ["priority"])
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_FILTER"


def test_parse_filters_accepts_valid_uuid_string() -> None:
    project_id = str(uuid.uuid4())
    filters = parse_filters({"project": project_id}, ["project"])
    assert filters.values == {"project": project_id}


def test_parse_filters_rejects_invalid_uuid_string() -> None:
    try:
        parse_filters({"project": "not-a-uuid"}, ["project"])
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_FILTER"


def test_parse_filters_accepts_valid_iso8601_timestamp() -> None:
    filters = parse_filters({"created_after": "2026-07-10T00:00:00+00:00"}, ["created_after"])
    assert filters.values == {"created_after": "2026-07-10T00:00:00+00:00"}


def test_parse_filters_rejects_invalid_timestamp() -> None:
    try:
        parse_filters({"created_after": "not-a-date"}, ["created_after"])
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_FILTER"


def test_parse_filters_accepts_valid_boolean() -> None:
    filters = parse_filters({"active_only": True}, ["active_only"])
    assert filters.values == {"active_only": True}


def test_parse_filters_rejects_non_boolean_value() -> None:
    try:
        parse_filters({"active_only": "yes"}, ["active_only"])
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_FILTER"


def test_parse_filters_rejects_unknown_field_name() -> None:
    try:
        parse_filters({}, ["not_a_real_filter_field"])
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_default_and_max_limit_constants() -> None:
    assert DEFAULT_LIMIT == 50
    assert MAX_LIMIT == 200


def _work_item(
    *,
    work_kind,
    priority_nice=0,
    ready=True,
    requires_runtime=False,
    is_blocker=False,
    bug_severity=None,
    step_uuid=None,
    title="item",
):
    return WorkItem(
        work_kind=work_kind,
        source_uuid=uuid.uuid4(),
        title=title,
        priority_nice=priority_nice,
        ready=ready,
        requires_runtime=requires_runtime,
        is_blocker=is_blocker,
        bug_severity=bug_severity,
        step_uuid=step_uuid,
    )


def test_order_queue_blocker_before_non_blocker() -> None:
    availability = ResourceAvailability()
    plain = _work_item(work_kind=WorkKind.TODO.value, is_blocker=False)
    blocker = _work_item(work_kind=WorkKind.BUG_INVESTIGATION.value, is_blocker=True)

    ordered = order_queue([plain, blocker], availability)

    assert ordered[0] is blocker
    assert ordered[1] is plain


def test_order_queue_lower_nice_sorts_first() -> None:
    availability = ResourceAvailability()
    low = _work_item(work_kind=WorkKind.TODO.value, priority_nice=-5)
    high = _work_item(work_kind=WorkKind.TODO.value, priority_nice=0)

    ordered = order_queue([high, low], availability)

    assert ordered[0] is low
    assert ordered[1] is high


def test_order_queue_launchable_before_unlaunchable() -> None:
    availability = ResourceAvailability()
    launchable = _work_item(work_kind=WorkKind.TODO.value, ready=True)
    not_ready = _work_item(work_kind=WorkKind.TODO.value, ready=False)

    ordered = order_queue([not_ready, launchable], availability)

    assert ordered[0] is launchable
    assert ordered[1] is not_ready


def test_pause_dependent_as_blocker_bug_pauses_ready_as() -> None:
    step_uuid = uuid.uuid4()
    bug = _work_item(work_kind=WorkKind.BUG_INVESTIGATION.value, is_blocker=True, step_uuid=step_uuid)
    as_ready = _work_item(work_kind=WorkKind.AS_READY.value, step_uuid=step_uuid)

    result = pause_dependent_as([bug, as_ready])

    paused_as = [it for it in result if it.work_kind == WorkKind.AS_READY.value][0]
    assert paused_as.paused is True
    assert paused_as.paused_reason is not None


def test_pause_dependent_as_high_priority_todo_pauses_ready_as() -> None:
    step_uuid = uuid.uuid4()
    todo = _work_item(work_kind=WorkKind.TODO.value, priority_nice=-10, step_uuid=step_uuid)
    as_ready = _work_item(work_kind=WorkKind.AS_READY.value, step_uuid=step_uuid)

    result = pause_dependent_as([todo, as_ready])

    paused_as = [it for it in result if it.work_kind == WorkKind.AS_READY.value][0]
    assert paused_as.paused is True


def test_pause_dependent_as_no_pause_without_blocker_or_high_priority() -> None:
    step_uuid = uuid.uuid4()
    todo = _work_item(work_kind=WorkKind.TODO.value, priority_nice=0, step_uuid=step_uuid)
    as_ready = _work_item(work_kind=WorkKind.AS_READY.value, step_uuid=step_uuid)

    result = pause_dependent_as([todo, as_ready])

    paused_as = [it for it in result if it.work_kind == WorkKind.AS_READY.value][0]
    assert paused_as.paused is False


def test_work_queue_status_frozensets() -> None:
    assert wq.TODO_ACTIVE_STATUSES == frozenset({"open", "ready", "in_progress", "blocked"})
    assert wq.BUG_OPEN_STATUSES == frozenset(
        {"reported", "triaged", "confirmed", "fixing", "propagating", "reopened"}
    )
    assert wq.FIX_UNFINISHED_STATUSES == frozenset({"proposed", "in_progress", "implemented", "partial"})
    assert wq.PROPAGATION_OPEN_STATUSES == frozenset(
        {"pending", "ready", "in_progress", "blocked", "failed"}
    )
    assert wq.ATTEMPT_VERIFICATION_STATUSES == frozenset({"needs_review"})
    assert wq.REVIEW_OPEN_STATUSES == frozenset({"changes_requested", "needs_owner_decision", "escalated"})


def _record(status):
    return types.SimpleNamespace(status=status)


@contextlib.contextmanager
def _patched_sources():
    def mapper(kind):
        return lambda record: _work_item(work_kind=kind)

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(wq, "work_item_from_as_ready", mapper(WorkKind.AS_READY.value)))
        stack.enter_context(patch.object(wq, "work_item_from_todo", mapper(WorkKind.TODO.value)))
        stack.enter_context(
            patch.object(wq, "work_item_from_bug_report", mapper(WorkKind.BUG_INVESTIGATION.value))
        )
        stack.enter_context(patch.object(wq, "work_item_from_bug_fix", mapper(WorkKind.BUG_FIX.value)))
        stack.enter_context(patch.object(wq, "work_item_from_propagation", mapper(WorkKind.PROPAGATION.value)))
        stack.enter_context(
            patch.object(wq, "work_item_from_execution_attempt", mapper(WorkKind.VERIFICATION.value))
        )
        stack.enter_context(patch.object(wq, "work_item_from_review_result", mapper(WorkKind.REVIEW.value)))
        stack.enter_context(patch.object(wq, "work_item_from_escalation", mapper(WorkKind.ESCALATION.value)))
        yield stack


def test_build_unified_queue_aggregates_only_actionable_records() -> None:
    with _patched_sources(), contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(wq, "list_todos", lambda conn, **k: [_record("open"), _record("closed")]))
        stack.enter_context(patch.object(wq, "list_bugs", lambda conn, **k: [_record("confirmed"), _record("closed")]))
        stack.enter_context(patch.object(wq, "list_bug_fixes", lambda conn, **k: [_record("proposed"), _record("verified")]))
        stack.enter_context(
            patch.object(wq, "list_bug_fix_propagations", lambda conn, **k: [_record("pending"), _record("done")])
        )
        stack.enter_context(
            patch.object(wq, "list_execution_attempts", lambda conn, **k: [_record("needs_review"), _record("succeeded")])
        )
        stack.enter_context(
            patch.object(wq, "list_review_results", lambda conn, **k: [_record("changes_requested"), _record("accepted")])
        )
        stack.enter_context(patch.object(wq, "list_escalations", lambda conn, **k: [_record("open")]))

        result = build_unified_queue(
            None, as_ready=[types.SimpleNamespace()], availability=ResourceAvailability()
        )

    assert len(result) == 8


def test_build_unified_queue_skips_inactive_records() -> None:
    with _patched_sources(), contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(wq, "list_todos", lambda conn, **k: [_record("closed")]))
        stack.enter_context(patch.object(wq, "list_bugs", lambda conn, **k: [_record("closed")]))
        stack.enter_context(patch.object(wq, "list_bug_fixes", lambda conn, **k: [_record("verified")]))
        stack.enter_context(patch.object(wq, "list_bug_fix_propagations", lambda conn, **k: [_record("done")]))
        stack.enter_context(patch.object(wq, "list_execution_attempts", lambda conn, **k: [_record("succeeded")]))
        stack.enter_context(patch.object(wq, "list_review_results", lambda conn, **k: [_record("accepted")]))
        stack.enter_context(patch.object(wq, "list_escalations", lambda conn, **k: []))

        result = build_unified_queue(None, as_ready=[], availability=ResourceAvailability())

    assert result == []
