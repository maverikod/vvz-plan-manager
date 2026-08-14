"""Store-layer regression suite for the group-3 anchoring-symmetry fix (bugs
2c568c0c/5c0ddc16): plan_manager.storage.entity_reanchor_store.
reanchor_owner_form_entity, the shared implementation behind wish_reanchor,
calendar_entry_reanchor and escalation_reanchor -- routing an owner-form
anchor kind through the already-pinned reanchor_guard.guard_owner_update, and
a ref_id-bearing anchor kind (execution_attempt/review_result/bug/bug_fix)
through a direct discriminated UPDATE instead (see entity_reanchor_store.py's
module docstring for why guard_owner_update's owner-form is deliberately not
used for those four).

Comment's own dedicated reanchor_comment path (always a direct UPDATE,
runtime_comment is NOT in reanchor_guard.OWNER_UPDATE_TABLES) is covered
separately in tests/test_group3_comment_reanchor_store.py, to keep both
files under the project's 400-line-per-file guideline.

Fake psycopg connections only; no live PostgreSQL instance is required -- the
same technique tests/test_bug_5c0ddc16_wish_reanchor_guard.py already pins for
guard_owner_update itself.

Covers, per the group-3 acceptance checklist:
  (a) in-place UPDATE only (uuid/created_at preserved, no DELETE+INSERT);
  (b) a frozen plan target is refused before any write;
  (c) the audit record carries old_anchor/new_anchor/changed_by;
  (e) detaching to anchor_type "none" works.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.domain import reanchor_guard
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
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
        table_by_id: dict[uuid.UUID, str] | None = None,
        frozen_plans: frozenset[uuid.UUID] = frozenset(),
        frozen_steps: frozenset[uuid.UUID] = frozenset(),
        completed_plans: frozenset[uuid.UUID] = frozenset(),
    ) -> None:
        self._table_by_id = table_by_id or {}
        self._frozen_plans = frozen_plans
        self._frozen_steps = frozen_steps
        self._completed_plans = completed_plans
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple = ()):
        self.statements.append((sql, params))

        if "FROM entity_identity WHERE id = %s" in sql:
            entity_id = params[0]
            table_name = self._table_by_id.get(entity_id)
            if table_name is None:
                return _Cur(None)
            return _Cur((entity_id, table_name, "entity", "entity", None, None, None))
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


class _FakeWish:
    TABLE_NAME = "wish_item"


class _FakeCalendarEntry:
    TABLE_NAME = "calendar_entry"


class _FakeEscalation:
    TABLE_NAME = "escalation"


def _entity(cls, **overrides):
    obj = cls()
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
def _no_op_relation_index(monkeypatch):
    """guard_owner_update records relation_index edges for every REFERENCE_
    CATALOG-listed anchor column -- irrelevant to what this suite verifies
    (the UPDATE/audit/frozen-guard mechanics) and not itself under test here;
    stub it so the fixture conn above never needs to answer its SQL."""
    monkeypatch.setattr(
        reanchor_guard.relation_index_store, "record_reference", lambda *a, **k: None
    )


@pytest.fixture(autouse=True)
def _capture_audit(monkeypatch):
    captured: dict = {}

    def _fake_record_runtime_change(conn, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(entity_reanchor_store, "record_runtime_change", _fake_record_runtime_change)
    return captured


_OWNER_FORM_CASES = [
    (_FakeWish, "wish_item", "WISH_NOT_FOUND", "wish"),
    (_FakeCalendarEntry, "calendar_entry", "CALENDAR_ENTRY_NOT_FOUND", "calendar_entry"),
    (_FakeEscalation, "escalation", "ESCALATION_NOT_FOUND", "escalation"),
]


@pytest.mark.parametrize("cls,table_name,not_found_code,entity_type", _OWNER_FORM_CASES)
def test_detach_to_none_is_update_only_no_delete_insert(cls, table_name, not_found_code, entity_type):
    entity_uuid = uuid.uuid4()
    existing = _entity(cls, primary_anchor_type="project", anchor_project_id=uuid.uuid4())
    updated = _entity(cls, primary_anchor_type="none")
    conn = _FakeConn(table_by_id={entity_uuid: table_name})

    result = entity_reanchor_store.reanchor_owner_form_entity(
        conn,
        entity_uuid,
        changed_by="alice",
        new_anchor=PrimaryAnchor(anchor_type="none"),
        entity_type=entity_type,
        get_entity=_get_entity_sequence(existing, updated),
        not_found_code=not_found_code,
    )
    assert result is updated

    update_statements = [s for s in conn.statements if s[0].startswith("UPDATE")]
    assert len(update_statements) == 1
    sql, params = update_statements[0]
    assert sql.startswith(f"UPDATE {table_name} SET ")
    set_clause = sql.split(" SET ", 1)[1].split(" WHERE", 1)[0]
    set_columns = [assignment.strip() for assignment in set_clause.split(",")]
    assert "uuid = %s" not in set_columns  # the primary key itself is never assigned
    assert "created_at" not in sql
    assert params[-1] == entity_uuid
    for sql, _params in conn.statements:
        assert f"DELETE FROM {table_name}" not in sql
        assert f"INSERT INTO {table_name}" not in sql


@pytest.mark.parametrize("cls,table_name,not_found_code,entity_type", _OWNER_FORM_CASES)
def test_refuses_frozen_plan_target_before_any_write(cls, table_name, not_found_code, entity_type):
    entity_uuid = uuid.uuid4()
    frozen_plan = uuid.uuid4()
    existing = _entity(cls)
    conn = _FakeConn(
        table_by_id={entity_uuid: table_name, frozen_plan: "plan"},
        frozen_plans=frozenset({frozen_plan}),
    )

    with pytest.raises(FrozenTruthMutationError):
        entity_reanchor_store.reanchor_owner_form_entity(
            conn,
            entity_uuid,
            changed_by="alice",
            new_anchor=PrimaryAnchor(anchor_type="plan", plan_uuid=frozen_plan),
            entity_type=entity_type,
            get_entity=_get_entity_sequence(existing),
            not_found_code=not_found_code,
        )

    assert not any(s[0].startswith("UPDATE") for s in conn.statements)


@pytest.mark.parametrize("cls,table_name,not_found_code,entity_type", _OWNER_FORM_CASES)
def test_records_audit_with_old_new_anchor_and_changed_by(
    cls, table_name, not_found_code, entity_type, _capture_audit
):
    entity_uuid = uuid.uuid4()
    old_project = uuid.uuid4()
    existing = _entity(cls, primary_anchor_type="project", anchor_project_id=old_project)
    updated = _entity(cls, primary_anchor_type="none")
    conn = _FakeConn(table_by_id={entity_uuid: table_name})

    entity_reanchor_store.reanchor_owner_form_entity(
        conn,
        entity_uuid,
        changed_by="alice",
        new_anchor=PrimaryAnchor(anchor_type="none"),
        entity_type=entity_type,
        get_entity=_get_entity_sequence(existing, updated),
        not_found_code=not_found_code,
    )

    assert _capture_audit["entity_type"] == entity_type
    assert _capture_audit["entity_id"] == entity_uuid
    assert _capture_audit["action"] == "update"
    assert _capture_audit["changed_by"] == "alice"
    changed_fields = _capture_audit["changed_fields"]
    assert changed_fields["old_anchor"]["anchor_type"] == "project"
    assert changed_fields["old_anchor"]["project_id"] == str(old_project)
    assert changed_fields["new_anchor"]["anchor_type"] == "none"
    assert changed_fields["new_anchor"]["project_id"] is None


def test_not_found_raises_domain_command_error():
    from plan_manager.commands.errors import DomainCommandError

    entity_uuid = uuid.uuid4()
    conn = _FakeConn()
    with pytest.raises(DomainCommandError) as exc_info:
        entity_reanchor_store.reanchor_owner_form_entity(
            conn,
            entity_uuid,
            changed_by="alice",
            new_anchor=PrimaryAnchor(anchor_type="none"),
            entity_type="wish",
            get_entity=lambda conn, ref: None,
            not_found_code="WISH_NOT_FOUND",
        )
    assert exc_info.value.code == "WISH_NOT_FOUND"


def test_execution_attempt_ref_uses_direct_update_not_owner_form():
    """execution_attempt/review_result/bug/bug_fix are deliberately routed
    through the direct-UPDATE branch, not guard_owner_update's owner-form --
    see entity_reanchor_store's module docstring. No entity_identity lookup
    for entity_ref occurs (table_by_id is empty here, yet the move still
    succeeds), proving guard_owner_update is never called for this kind."""
    entity_uuid = uuid.uuid4()
    ref_id = uuid.uuid4()
    existing = _entity(_FakeWish)
    updated = _entity(_FakeWish, primary_anchor_type="execution_attempt", anchor_ref_id=ref_id)
    conn = _FakeConn()  # empty table_by_id: an entity_identity lookup would raise NotFoundError

    result = entity_reanchor_store.reanchor_owner_form_entity(
        conn,
        entity_uuid,
        changed_by="alice",
        new_anchor=PrimaryAnchor(anchor_type="execution_attempt", ref_id=ref_id),
        entity_type="wish",
        get_entity=_get_entity_sequence(existing, updated),
        not_found_code="WISH_NOT_FOUND",
    )
    assert result is updated
    update_statements = [s for s in conn.statements if s[0].startswith("UPDATE")]
    assert len(update_statements) == 1
    assert update_statements[0][0].startswith("UPDATE wish_item SET ")
    assert not any("entity_identity" in s[0] for s in conn.statements)
