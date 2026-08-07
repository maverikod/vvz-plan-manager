"""Regression suite for CR-7 G-007/T-001/A-003: the owner-form surface added
alongside plan_manager.domain.primary_anchor's legacy anchor surface.

Covers: resolve_owner's registry-backed resolution per anchor kind,
owner-form -> legacy-column normalization (including root outcomes for
None/path owners), owner-change acyclicity delegation to the admission
collaborator, and the owner-filtered query predicate helper.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.primary_anchor import (
    InvalidAnchorError,
    PrimaryAnchor,
    PrimaryAnchorType,
    anchor_to_columns,
    owner_filter_predicate,
    owner_form_to_anchor,
    owner_form_to_columns,
    resolve_owner,
    validate_owner_change,
)
from plan_manager.storage.errors import NotFoundError


class _FakeCursor:
    def __init__(self, row) -> None:
        self._row = row

    def fetchone(self):
        return self._row


class _RegistryConn:
    """Fake conn serving entity_identity rows for a caller-supplied
    {uuid: table_name} map, plus canned answers for the other validate_anchor
    collaborator queries (existence checks, plan-completed guard, step
    membership) so owner_form_to_columns's internal validate_anchor call
    always succeeds against a UUID this fixture knows about."""

    def __init__(self, table_by_id: dict[uuid.UUID, str]) -> None:
        self._table_by_id = table_by_id
        self.queries: list[str] = []

    def execute(self, sql: str, params=()):
        self.queries.append(sql)
        if "FROM entity_identity" in sql:
            entity_id = params[0]
            table_name = self._table_by_id.get(entity_id)
            if table_name is None:
                return _FakeCursor(None)
            return _FakeCursor(
                (entity_id, table_name, "entity", "created", None, None, None)
            )
        if "SELECT completed FROM plan" in sql:
            return _FakeCursor((False,))
        if sql.startswith("SELECT uuid FROM step"):
            return _FakeCursor((params[0],))
        if sql.startswith("SELECT 1 FROM"):
            return _FakeCursor((1,))
        raise AssertionError(f"unexpected query in fixture: {sql}")


class _RefusingConn:
    """A conn that raises if queried at all -- used to prove resolve_owner
    never touches the registry for plan/step/revision/project/file/none
    kinds, only for the five ref_id-bearing kinds."""

    def execute(self, sql: str, params=()):
        raise AssertionError(f"resolve_owner must not query the database for this kind: {sql}")


# ---------------------------------------------------------------------------
# resolve_owner: direct-field kinds never touch the registry.
# ---------------------------------------------------------------------------

def test_resolve_owner_plan_anchor_returns_plan_uuid_without_registry_lookup() -> None:
    plan_uuid = uuid.uuid4()
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.PLAN.value, plan_uuid=plan_uuid)
    assert resolve_owner(_RefusingConn(), anchor) == plan_uuid


def test_resolve_owner_step_anchor_returns_step_uuid_without_registry_lookup() -> None:
    step_uuid = uuid.uuid4()
    anchor = PrimaryAnchor(
        anchor_type=PrimaryAnchorType.STEP.value,
        plan_uuid=uuid.uuid4(),
        step_uuid=step_uuid,
    )
    assert resolve_owner(_RefusingConn(), anchor) == step_uuid


def test_resolve_owner_revision_anchor_returns_revision_uuid_without_registry_lookup() -> None:
    revision_uuid = uuid.uuid4()
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.REVISION.value, revision_uuid=revision_uuid)
    assert resolve_owner(_RefusingConn(), anchor) == revision_uuid


def test_resolve_owner_project_anchor_returns_external_id_verbatim_without_registry_lookup() -> None:
    project_id = uuid.uuid4()
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.PROJECT.value, project_id=project_id)
    assert resolve_owner(_RefusingConn(), anchor) == project_id


def test_resolve_owner_file_anchor_is_a_root() -> None:
    anchor = PrimaryAnchor(
        anchor_type=PrimaryAnchorType.FILE.value, project_id=uuid.uuid4(), file_path="src/module.py"
    )
    assert resolve_owner(_RefusingConn(), anchor) is None


def test_resolve_owner_none_anchor_is_a_root() -> None:
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.NONE.value)
    assert resolve_owner(_RefusingConn(), anchor) is None


# ---------------------------------------------------------------------------
# resolve_owner: the five ref_id-bearing kinds resolve THROUGH the registry.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "anchor_type,table_name",
    [
        (PrimaryAnchorType.EXECUTION_ATTEMPT.value, "execution_attempt"),
        (PrimaryAnchorType.REVIEW_RESULT.value, "review_result"),
        (PrimaryAnchorType.BUG.value, "bug_report"),
        (PrimaryAnchorType.BUG_FIX.value, "bug_fix"),
        (PrimaryAnchorType.TODO.value, "todo_item"),
    ],
)
def test_resolve_owner_ref_bearing_kinds_resolve_through_the_registry(anchor_type, table_name) -> None:
    ref_id = uuid.uuid4()
    conn = _RegistryConn({ref_id: table_name})
    anchor = PrimaryAnchor(anchor_type=anchor_type, ref_id=ref_id)
    assert resolve_owner(conn, anchor) == ref_id
    assert any("FROM entity_identity" in q for q in conn.queries)


def test_resolve_owner_rejects_ref_id_that_resolves_to_a_different_table() -> None:
    ref_id = uuid.uuid4()
    # Claimed as a "bug" anchor, but the registry says this id actually
    # belongs to todo_item -- the registry wins over the discriminator.
    conn = _RegistryConn({ref_id: "todo_item"})
    anchor = PrimaryAnchor(anchor_type=PrimaryAnchorType.BUG.value, ref_id=ref_id)
    with pytest.raises(InvalidAnchorError):
        resolve_owner(conn, anchor)


# ---------------------------------------------------------------------------
# owner-form normalization -> legacy columns, including root outcomes.
# ---------------------------------------------------------------------------

def test_owner_form_none_owner_no_path_normalizes_to_none_root() -> None:
    conn = _RegistryConn({})
    columns = owner_form_to_columns(conn, None)
    assert columns == anchor_to_columns(PrimaryAnchor(anchor_type=PrimaryAnchorType.NONE.value))


def test_owner_form_none_owner_with_path_normalizes_to_file_root_with_descriptive_path() -> None:
    conn = _RegistryConn({})
    project_id = uuid.uuid4()
    columns = owner_form_to_columns(conn, None, project_id=project_id, path="src/module.py")
    expected = anchor_to_columns(
        PrimaryAnchor(anchor_type=PrimaryAnchorType.FILE.value, project_id=project_id, file_path="src/module.py")
    )
    assert columns == expected
    assert columns["primary_anchor_type"] == "file"
    assert columns["anchor_project_id"] == project_id
    assert columns["anchor_file_path"] == "src/module.py"


def test_owner_form_none_owner_with_path_but_no_project_id_is_rejected() -> None:
    conn = _RegistryConn({})
    with pytest.raises(InvalidAnchorError):
        owner_form_to_anchor(conn, None, path="src/module.py")


def test_owner_form_plan_owner_normalizes_to_legacy_plan_columns() -> None:
    plan_uuid = uuid.uuid4()
    conn = _RegistryConn({plan_uuid: "plan"})
    columns = owner_form_to_columns(conn, plan_uuid)
    assert columns["primary_anchor_type"] == "plan"
    assert columns["anchor_plan_uuid"] == plan_uuid


def test_owner_form_step_owner_requires_plan_uuid_and_populates_both_legacy_columns() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    conn = _RegistryConn({step_uuid: "step"})
    columns = owner_form_to_columns(conn, step_uuid, plan_uuid=plan_uuid)
    assert columns["primary_anchor_type"] == "step"
    assert columns["anchor_plan_uuid"] == plan_uuid
    assert columns["anchor_step_uuid"] == step_uuid


def test_owner_form_step_owner_without_plan_uuid_is_rejected() -> None:
    step_uuid = uuid.uuid4()
    conn = _RegistryConn({step_uuid: "step"})
    with pytest.raises(InvalidAnchorError):
        owner_form_to_anchor(conn, step_uuid)


def test_owner_form_todo_owner_normalizes_to_legacy_ref_id_column() -> None:
    todo_uuid = uuid.uuid4()
    conn = _RegistryConn({todo_uuid: "todo_item"})
    columns = owner_form_to_columns(conn, todo_uuid)
    assert columns["primary_anchor_type"] == "todo"
    assert columns["anchor_ref_id"] == todo_uuid


def test_owner_form_unregistered_owner_normalizes_to_external_project_id() -> None:
    project_id = uuid.uuid4()
    conn = _RegistryConn({})  # empty registry: project_id is not a local row
    columns = owner_form_to_columns(conn, project_id)
    assert columns["primary_anchor_type"] == "project"
    assert columns["anchor_project_id"] == project_id


def test_owner_form_to_anchor_raises_not_found_error_is_caught_internally() -> None:
    # Sanity: the registry's own NotFoundError never leaks past normalization
    # for an unregistered owner -- it is caught and turned into "project".
    project_id = uuid.uuid4()
    conn = _RegistryConn({})
    anchor = owner_form_to_anchor(conn, project_id)
    assert isinstance(anchor, PrimaryAnchor)
    assert anchor.anchor_type == "project"


# ---------------------------------------------------------------------------
# Ownership-acyclicity validation delegates to the admission collaborator.
# ---------------------------------------------------------------------------

def test_validate_owner_change_delegates_to_admission_collaborator(monkeypatch) -> None:
    calls = []

    def _fake_ensure_owner_acyclic(current_owner_edges, *, entity_ref, new_owner_ref):
        calls.append((tuple(current_owner_edges), entity_ref, new_owner_ref))

    import plan_manager.domain.primary_anchor as primary_anchor_module

    monkeypatch.setattr(primary_anchor_module, "ensure_owner_acyclic", _fake_ensure_owner_acyclic)

    entity_ref = uuid.uuid4()
    new_owner_ref = uuid.uuid4()
    edges = (("child", "parent"),)
    validate_owner_change(entity_ref, new_owner_ref, edges)

    assert calls == [(edges, entity_ref, new_owner_ref)]


def test_validate_owner_change_detaching_to_root_never_cycles(monkeypatch) -> None:
    # Exercises the real collaborator (no fake) for the documented "None
    # never cycles" short-circuit in admission.ensure_owner_acyclic.
    entity_ref = uuid.uuid4()
    validate_owner_change(entity_ref, None, current_owner_edges=(("a", "b"), ("b", "a")))


# ---------------------------------------------------------------------------
# owner-filtered query helper: emits owner-column predicates.
# ---------------------------------------------------------------------------

def test_owner_filter_predicate_matches_owner_column_equality() -> None:
    owner = uuid.uuid4()
    predicate, params = owner_filter_predicate("owner", owner)
    assert predicate == "owner = %s"
    assert params == (owner,)


def test_owner_filter_predicate_matches_root_rows_with_is_null() -> None:
    predicate, params = owner_filter_predicate("owner_uuid", None)
    assert predicate == "owner_uuid IS NULL"
    assert params == ()


def test_owner_filter_predicate_uses_the_caller_supplied_owner_column_name() -> None:
    # bug_report's migration-0029 owner column is named owner_uuid, not
    # owner -- the helper must not hardcode a single column name.
    owner = uuid.uuid4()
    predicate, _ = owner_filter_predicate("owner_uuid", owner)
    assert predicate.startswith("owner_uuid")
