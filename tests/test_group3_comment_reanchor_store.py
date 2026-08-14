"""Store-layer regression suite for the group-3 anchoring-symmetry fix (bug
2c568c0c): plan_manager.storage.entity_reanchor_store.reanchor_comment.

Split out from tests/test_group3_owner_form_reanchor_store.py (which covers
wish_reanchor/calendar_entry_reanchor/escalation_reanchor's shared
reanchor_owner_form_entity path) to keep both files under the project's
400-line-per-file guideline; the two share the same fake-conn technique.

runtime_comment is deliberately NOT a member of
reanchor_guard.OWNER_UPDATE_TABLES (see entity_reanchor_store.py's module
docstring): a comment's anchor vocabulary differs from the legacy
PrimaryAnchorType family in exactly two ways -- "none" is rejected outright
(a comment always attaches to a subject) and "escalation" is accepted (with
its own ref_id-existence check) -- so reanchor_comment always applies a
direct discriminated UPDATE rather than guard_owner_update's owner-form.

Fake psycopg connections only; no live PostgreSQL instance is required.

Covers, per the group-3 acceptance checklist:
  (a) in-place UPDATE only (uuid/created_at preserved, no DELETE+INSERT);
  (b) a frozen step target is refused before any write;
  (c) the audit record carries old_anchor/new_anchor/changed_by;
  (d) "none" is rejected, and an "escalation" anchor's ref_id is checked
      against the escalation table.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.domain.runtime_validation import FrozenTruthMutationError, RuntimeValidationError
from plan_manager.storage import entity_reanchor_store


class _Cur:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(
        self,
        *,
        frozen_plans: frozenset[uuid.UUID] = frozenset(),
        frozen_steps: frozenset[uuid.UUID] = frozenset(),
        completed_plans: frozenset[uuid.UUID] = frozenset(),
    ) -> None:
        self._frozen_plans = frozen_plans
        self._frozen_steps = frozen_steps
        self._completed_plans = completed_plans
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()):
        self.statements.append((sql, params))

        if sql.startswith("SELECT completed FROM plan"):
            return _Cur((params[0] in self._completed_plans,))
        if sql.startswith("SELECT status FROM plan"):
            return _Cur(("frozen" if params[0] in self._frozen_plans else "draft",))
        if sql.startswith("SELECT status FROM step"):
            return _Cur(("frozen" if params[0] in self._frozen_steps else "draft",))
        if sql.startswith("SELECT 1 FROM"):
            return _Cur((1,))
        if sql.startswith("SELECT uuid FROM step"):
            return _Cur((params[0],))
        if sql.startswith("UPDATE "):
            return _Cur(None)
        raise AssertionError(f"unexpected query in this fixture: {sql!r} params={params!r}")


_ANCHOR_ATTRS = (
    "primary_anchor_type", "anchor_project_id", "anchor_file_path", "anchor_plan_uuid",
    "anchor_revision_uuid", "anchor_step_uuid", "anchor_step_path", "anchor_ref_id",
)


class _FakeComment:
    TABLE_NAME = "runtime_comment"


def _entity(**overrides):
    obj = _FakeComment()
    values = {attr: None for attr in _ANCHOR_ATTRS}
    values["primary_anchor_type"] = "none"
    values.update(overrides)
    for key, value in values.items():
        setattr(obj, key, value)
    return obj


def _get_entity_sequence(*entities):
    state = {"i": 0}

    def _get(conn, ref):
        idx = min(state["i"], len(entities) - 1)
        state["i"] += 1
        return entities[idx]

    return _get


@pytest.fixture(autouse=True)
def _capture_audit(monkeypatch):
    captured: dict = {}

    def _fake_record_runtime_change(conn, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(entity_reanchor_store, "record_runtime_change", _fake_record_runtime_change)
    return captured


def test_rejects_none_anchor_type(monkeypatch):
    comment_uuid = uuid.uuid4()
    existing = _entity(primary_anchor_type="project", anchor_project_id=uuid.uuid4())
    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment", _get_entity_sequence(existing)
    )
    conn = _FakeConn()
    with pytest.raises(RuntimeValidationError):
        entity_reanchor_store.reanchor_comment(
            conn, comment_uuid, changed_by="alice", new_anchor=PrimaryAnchor(anchor_type="none")
        )
    assert not any(s[0].startswith("UPDATE") for s in conn.statements)


def test_project_anchor_is_update_only_no_delete_insert(monkeypatch):
    comment_uuid = uuid.uuid4()
    existing = _entity(primary_anchor_type="step", anchor_step_uuid=uuid.uuid4())
    updated = _entity(primary_anchor_type="project", anchor_project_id=uuid.uuid4())
    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment",
        _get_entity_sequence(existing, updated),
    )
    conn = _FakeConn()
    new_project = uuid.uuid4()

    result = entity_reanchor_store.reanchor_comment(
        conn,
        comment_uuid,
        changed_by="alice",
        new_anchor=PrimaryAnchor(anchor_type="project", project_id=new_project),
    )
    assert result is updated
    update_statements = [s for s in conn.statements if s[0].startswith("UPDATE")]
    assert len(update_statements) == 1
    sql, params = update_statements[0]
    assert sql.startswith("UPDATE runtime_comment SET ")
    set_clause = sql.split(" SET ", 1)[1].split(" WHERE", 1)[0]
    set_columns = [assignment.strip() for assignment in set_clause.split(",")]
    assert "uuid = %s" not in set_columns  # the primary key itself is never assigned
    assert "created_at" not in sql
    assert params[-1] == comment_uuid
    for sql, _params in conn.statements:
        assert "DELETE FROM runtime_comment" not in sql
        assert "INSERT INTO runtime_comment" not in sql


def test_escalation_anchor_checks_ref_exists(monkeypatch):
    comment_uuid = uuid.uuid4()
    escalation_uuid = uuid.uuid4()
    existing = _entity(primary_anchor_type="project", anchor_project_id=uuid.uuid4())
    updated = _entity(primary_anchor_type="escalation", anchor_ref_id=escalation_uuid)
    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment",
        _get_entity_sequence(existing, updated),
    )
    conn = _FakeConn()

    result = entity_reanchor_store.reanchor_comment(
        conn,
        comment_uuid,
        changed_by="alice",
        new_anchor=PrimaryAnchor(anchor_type="escalation", ref_id=escalation_uuid),
    )
    assert result is updated
    assert any(
        sql == "SELECT 1 FROM escalation WHERE uuid = %s" and params == (escalation_uuid,)
        for sql, params in conn.statements
    )


def test_refuses_frozen_step_target_before_any_write(monkeypatch):
    comment_uuid = uuid.uuid4()
    frozen_step = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    existing = _entity(primary_anchor_type="project", anchor_project_id=uuid.uuid4())
    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment", _get_entity_sequence(existing)
    )
    conn = _FakeConn(frozen_steps=frozenset({frozen_step}))

    with pytest.raises(FrozenTruthMutationError):
        entity_reanchor_store.reanchor_comment(
            conn,
            comment_uuid,
            changed_by="alice",
            new_anchor=PrimaryAnchor(anchor_type="step", plan_uuid=plan_uuid, step_uuid=frozen_step),
        )
    assert not any(s[0].startswith("UPDATE") for s in conn.statements)


def test_records_audit_with_old_new_anchor_and_changed_by(monkeypatch, _capture_audit):
    comment_uuid = uuid.uuid4()
    old_project = uuid.uuid4()
    new_project = uuid.uuid4()
    existing = _entity(primary_anchor_type="project", anchor_project_id=old_project)
    updated = _entity(primary_anchor_type="project", anchor_project_id=new_project)
    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment",
        _get_entity_sequence(existing, updated),
    )
    conn = _FakeConn()

    entity_reanchor_store.reanchor_comment(
        conn,
        comment_uuid,
        changed_by="bob",
        new_anchor=PrimaryAnchor(anchor_type="project", project_id=new_project),
    )

    assert _capture_audit["entity_type"] == "comment"
    assert _capture_audit["entity_id"] == comment_uuid
    assert _capture_audit["changed_by"] == "bob"
    changed_fields = _capture_audit["changed_fields"]
    assert changed_fields["old_anchor"]["project_id"] == str(old_project)
    assert changed_fields["new_anchor"]["project_id"] == str(new_project)


def test_not_found_raises_domain_command_error(monkeypatch):
    from plan_manager.commands.errors import DomainCommandError

    monkeypatch.setattr(
        "plan_manager.storage.runtime_comment_store.get_comment", lambda conn, ref: None
    )
    conn = _FakeConn()
    with pytest.raises(DomainCommandError) as exc_info:
        entity_reanchor_store.reanchor_comment(
            conn, uuid.uuid4(), changed_by="alice", new_anchor=PrimaryAnchor(anchor_type="project", project_id=uuid.uuid4())
        )
    assert exc_info.value.code == "COMMENT_NOT_FOUND"
