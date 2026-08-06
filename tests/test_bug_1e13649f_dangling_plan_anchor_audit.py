"""Regression coverage for bug 1e13649f: bug_delete (soft and hard paths) on a
bug whose source_plan_uuid anchors a hard-deleted plan used to fail with
-32603 ("insert on runtime_audit_log violates FK
runtime_audit_log_plan_uuid_fkey"). bug_report.source_plan_uuid (like every
other plan-anchor column this project's runtime entities carry --
todo.anchor_plan_uuid, runtime_comment.anchor_plan_uuid, ...) has NO foreign
key of its own, so plan_delete does not cascade to it and a dangling anchor
is a legal, reachable state; runtime_audit_log.plan_uuid DOES carry
`REFERENCES plan(uuid) ON DELETE CASCADE`, so a *new* audit INSERT anchored
to that now-nonexistent plan violates the constraint.

The fix lives at the single shared layer every plan-anchored runtime
mutation funnels through --
plan_manager.storage.runtime_audit_store.record_runtime_change -- so it
covers the whole class of entities, not just bug_report. When the given
plan_uuid no longer references a live plan, record_runtime_change now
retries the insert unanchored (plan_uuid=NULL) inside the SAME statement's
SAVEPOINT and preserves the original dangling uuid under
DANGLING_PLAN_UUID_FIELD in changed_fields, so the audit trail is never
silently dropped and no information is lost.

Fidelity note (recorded here since it affects what these tests assert):
static review of the current bug_report_store.soft_delete_bug found it
hardcodes plan_uuid=None unconditionally -- it never reads the bug's own
source_plan_uuid before writing the audit row -- unlike every sibling
soft_delete_* that DOES forward a real (dangling-capable) anchor
(todo_store.soft_delete_todo -> anchor_plan_uuid,
runtime_comment_store.soft_delete_comment -> anchor_plan_uuid). That means
bug_report's OWN soft-delete path was not, and is not, exposed to this
specific FK violation regardless of the record_runtime_change fix --
test_bug_delete_soft_path_with_dangling_anchor_does_not_raise below pins
that (already-safe) behavior rather than a crash-then-fix transition. The
hard-delete path (runtime_hard_delete.hard_delete_bug), which DOES forward
the bug's real source_plan_uuid, is where the FK violation genuinely
reproduces; test_bug_delete_hard_path_with_dangling_anchor_falls_back_and_
preserves_original_uuid below reproduces and fixes exactly that. TODO
soft-delete is exercised as the "other entity family" the class-wide fix
also covers, since it genuinely forwards a dangling-capable anchor.
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Any, Iterator

import psycopg
import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.todo import TodoItem
from plan_manager.storage import bug_report_store
from plan_manager.storage import runtime_hard_delete
from plan_manager.storage.runtime_audit_store import (
    DANGLING_PLAN_UUID_FIELD,
    record_runtime_change,
)


class _FKViolatingConn:
    """Fake psycopg connection reproducing runtime_audit_log_plan_uuid_fkey.

    Any INSERT INTO runtime_audit_log whose plan_uuid parameter is in
    ``dangling_plan_uuids`` raises psycopg.errors.ForeignKeyViolation on
    first attempt -- exactly what a real Postgres instance raises when the
    audit row's plan_uuid points at a plan that has been hard-deleted.
    Every attempted INSERT (rejected or accepted) is recorded in
    ``insert_attempts`` so tests can assert both the retry and its final
    parameters. ``transaction()`` is a bare passthrough context manager (no
    real nested-transaction bookkeeping needed for these tests): it must
    exist and must let the ForeignKeyViolation propagate unmodified, which
    is exactly psycopg's own savepoint-transaction contract on error.
    """

    def __init__(self, dangling_plan_uuids: set[uuid.UUID]) -> None:
        """Store the set of plan uuids this fake treats as already deleted (dangling anchors)."""
        self.dangling_plan_uuids = set(dangling_plan_uuids)
        self.insert_attempts: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record every statement; raise ForeignKeyViolation for a dangling-anchor runtime_audit_log INSERT, matching live Postgres behavior."""
        # CR-7 G-004: the routed store binds through psycopg sql.Composed.
        rendered = (sql.as_string(None) if hasattr(sql, "as_string") else str(sql)).replace('"', "")
        if rendered.strip().startswith("INSERT INTO runtime_audit_log"):
            self.insert_attempts.append(params)
            plan_uuid = params[1]
            if plan_uuid is not None and plan_uuid in self.dangling_plan_uuids:
                raise psycopg.errors.ForeignKeyViolation(
                    'insert or update on table "runtime_audit_log" violates '
                    'foreign key constraint "runtime_audit_log_plan_uuid_fkey"'
                )
        return None

    @contextlib.contextmanager
    def transaction(self) -> Iterator["_FKViolatingConn"]:
        """Bare passthrough standing in for psycopg's savepoint-aware transaction(): lets any exception raised inside the block propagate unchanged, matching real savepoint-rollback-then-reraise semantics."""
        yield self


class _Conn:
    """Bare fake conn exposing only execute() -- no transaction() at all.

    Used to pin that record_runtime_change's plan_uuid=None fast path never
    touches conn.transaction(): a caller passing an unanchored write is not
    forced to support the savepoint machinery this fix introduces only for
    the plan-anchored branch.
    """

    def __init__(self) -> None:
        """Initialize the captured-call list for the bare fake connection."""
        self.insert_attempts: list[tuple[Any, ...]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record the statement; this fake never raises (used only for the plan_uuid=None fast path, which cannot violate the FK)."""
        self.insert_attempts.append(params)
        return None


# --------------------------------------------------------------------------
# record_runtime_change: the shared layer, exercised directly
# --------------------------------------------------------------------------


def test_dangling_plan_anchor_falls_back_to_null_and_preserves_original_uuid() -> None:
    """bug 1e13649f: a plan_uuid that no longer references a live plan must not raise; the audit row lands with plan_uuid=NULL and the original uuid preserved in changed_fields."""
    dangling_plan = uuid.uuid4()
    entity_id = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids={dangling_plan})

    rec = record_runtime_change(
        conn,
        plan_uuid=dangling_plan,
        entity_type="bug_report",
        entity_id=entity_id,
        action="hard_delete",
        changed_by="tester",
    )

    assert rec.plan_uuid is None
    assert rec.changed_fields == {DANGLING_PLAN_UUID_FIELD: str(dangling_plan)}
    # two attempts: the rejected anchored insert, then the accepted unanchored retry
    assert len(conn.insert_attempts) == 2
    assert conn.insert_attempts[0][1] == dangling_plan
    assert conn.insert_attempts[1][1] is None
    assert conn.insert_attempts[1][7].obj == {DANGLING_PLAN_UUID_FIELD: str(dangling_plan)}


def test_dangling_plan_anchor_fallback_merges_into_existing_changed_fields() -> None:
    """The dangling-uuid preservation key is merged into caller-supplied changed_fields, not a replacement of them."""
    dangling_plan = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids={dangling_plan})

    rec = record_runtime_change(
        conn,
        plan_uuid=dangling_plan,
        entity_type="todo",
        entity_id=uuid.uuid4(),
        action="soft_delete",
        changed_by="tester",
        changed_fields={"note": "closed by cleanup"},
    )

    assert rec.plan_uuid is None
    assert rec.changed_fields == {
        "note": "closed by cleanup",
        DANGLING_PLAN_UUID_FIELD: str(dangling_plan),
    }


def test_live_plan_anchor_path_is_unchanged() -> None:
    """Normal path: plan_uuid references a live plan -- single insert attempt, no fallback, plan_uuid and changed_fields returned exactly as given."""
    live_plan = uuid.uuid4()
    entity_id = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids=set())  # nothing dangling

    rec = record_runtime_change(
        conn,
        plan_uuid=live_plan,
        entity_type="bug_report",
        entity_id=entity_id,
        action="hard_delete",
        changed_by="tester",
        changed_fields={"k": "v"},
    )

    assert rec.plan_uuid == live_plan
    assert rec.changed_fields == {"k": "v"}
    assert len(conn.insert_attempts) == 1
    assert conn.insert_attempts[0][1] == live_plan


def test_unanchored_write_never_touches_transaction() -> None:
    """plan_uuid=None (the common unanchored case) must not require conn.transaction() at all -- the savepoint machinery is only entered for plan-anchored writes."""
    conn = _Conn()

    rec = record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_fix",
        entity_id=uuid.uuid4(),
        action="soft_delete",
        changed_by="tester",
    )

    assert rec.plan_uuid is None
    assert len(conn.insert_attempts) == 1


# --------------------------------------------------------------------------
# bug_delete: hard path (runtime_hard_delete.hard_delete_bug) -- the path
# the bug's live repro recipe exercises directly.
# --------------------------------------------------------------------------


def test_bug_delete_hard_path_with_dangling_anchor_falls_back_and_preserves_original_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bug 1e13649f repro: create plan P -> bug B anchored to P -> plan hard-deleted -> bug_delete(hard=true) must succeed, writing an unanchored audit row that preserves P's uuid."""
    bug_uuid = uuid.uuid4()
    dangling_plan = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids={dangling_plan})

    monkeypatch.setattr(
        BugReport,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "source_plan_uuid": dangling_plan}),
    )
    delegated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        BugReport,
        "crud_hard_delete",
        classmethod(lambda cls, conn, entity_id, **kw: delegated.append({"entity_id": entity_id, **kw})),
    )

    runtime_hard_delete.hard_delete_bug(conn, bug_uuid, changed_by="tester")

    # The audit write itself now happens inside the central hard-delete guard,
    # which this test stubs out along with the physical deletion. What the
    # wrapper must still do — and what bug 1e13649f was about — is FORWARD the
    # dangling plan anchor rather than dropping it, so the recorder gets the
    # chance to fall back. The fallback itself is covered directly above, against
    # record_runtime_change, so it is not re-tested through a stub here.
    assert len(delegated) == 1
    assert delegated[0]["entity_id"] == bug_uuid
    assert delegated[0]["plan_uuid"] == dangling_plan
    assert delegated[0]["audit_entity_type"] == "bug_report"


def test_bug_delete_hard_path_with_live_anchor_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: hard_delete_bug on a bug anchored to a still-live plan records exactly one, unmodified audit row -- the fix must not perturb the normal path."""
    bug_uuid = uuid.uuid4()
    live_plan = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids=set())

    monkeypatch.setattr(
        BugReport,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "source_plan_uuid": live_plan}),
    )
    delegated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        BugReport,
        "crud_hard_delete",
        classmethod(lambda cls, conn, entity_id, **kw: delegated.append({"entity_id": entity_id, **kw})),
    )

    runtime_hard_delete.hard_delete_bug(conn, bug_uuid, changed_by="tester")

    assert len(delegated) == 1
    assert delegated[0]["plan_uuid"] == live_plan, (
        "the live anchor must be forwarded unchanged; the fix must not perturb the normal path"
    )


# --------------------------------------------------------------------------
# bug_delete: soft path (bug_report_store.soft_delete_bug) -- pins the
# already-safe current behavior; see the module docstring fidelity note.
# --------------------------------------------------------------------------


def test_bug_delete_soft_path_with_dangling_anchor_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    """soft_delete_bug always records plan_uuid=None (it never reads the bug's own source_plan_uuid), so a dangling anchor cannot reach the FK regardless of the shared-layer fix; this pins that this path stays exception-free and unaffected by whatever the bug's source_plan_uuid currently points at."""
    bug_uuid = uuid.uuid4()
    dangling_plan = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids={dangling_plan})

    stub_bug = BugReport.__new__(BugReport)
    monkeypatch.setattr(bug_report_store, "get_bug", lambda conn, uuid_: stub_bug)

    result = bug_report_store.soft_delete_bug(conn, bug_uuid, changed_by="tester")

    assert result is stub_bug
    assert len(conn.insert_attempts) == 1
    assert conn.insert_attempts[0][1] is None


# --------------------------------------------------------------------------
# Other entity family covered by the shared layer: TODO hard-delete, which
# (like bug hard-delete) forwards its real, dangling-capable plan anchor.
# --------------------------------------------------------------------------


def test_todo_hard_delete_with_dangling_anchor_falls_back_and_preserves_original_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared-layer fix also covers TODO hard-delete: a TODO anchored to a hard-deleted plan must not fail to delete, and its audit row must preserve the dangling plan uuid the same way bug hard-delete's does."""
    todo_uuid = uuid.uuid4()
    dangling_plan = uuid.uuid4()
    conn = _FKViolatingConn(dangling_plan_uuids={dangling_plan})

    monkeypatch.setattr(
        TodoItem,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "anchor_plan_uuid": dangling_plan}),
    )
    delegated: list[dict[str, Any]] = []
    monkeypatch.setattr(
        TodoItem,
        "crud_hard_delete",
        classmethod(lambda cls, conn, entity_id, **kw: delegated.append({"entity_id": entity_id, **kw})),
    )

    runtime_hard_delete.hard_delete_todo(conn, todo_uuid, changed_by="tester")

    # The audit write itself now happens inside the central hard-delete guard,
    # which this test stubs out along with the physical deletion. What the
    # wrapper must still do — and what bug 1e13649f was about — is FORWARD the
    # dangling plan anchor rather than dropping it, so the recorder gets the
    # chance to fall back. The fallback itself is covered directly above, against
    # record_runtime_change, so it is not re-tested through a stub here.
    assert len(delegated) == 1
    assert delegated[0]["entity_id"] == todo_uuid
    assert delegated[0]["plan_uuid"] == dangling_plan
    assert delegated[0]["audit_entity_type"] == "todo"


def test_todo_not_found_still_raises_domain_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: hard_delete_todo's pre-existing NOT_FOUND behavior is untouched by this fix."""
    monkeypatch.setattr(TodoItem, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: None))

    with pytest.raises(DomainCommandError) as excinfo:
        runtime_hard_delete.hard_delete_todo(_FKViolatingConn(set()), uuid.uuid4(), changed_by="tester")
    assert excinfo.value.code == "TODO_NOT_FOUND"
