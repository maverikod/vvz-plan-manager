"""Delegation suite for the migrated plan-truth stores (CR-6 G-003/T-003).

Fakes only; no live database. Asserts that each migrated store DELEGATES to its
entity's crud_* classmethods instead of re-implementing SQL, and that the
migration preserved what callers depend on: the public signature, the audit
record, and the jsonb bind wrapping.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess
import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.wish import WishItem
from plan_manager.storage import bug_fix_store, calendar_entry_store, todo_store, wish_store

_NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)

_MIGRATED = [
    (wish_store, WishItem),
    (calendar_entry_store, CalendarEntry),
    (bug_fix_store, BugFix),
    (todo_store, TodoItem),
]

# jsonb columns per store. psycopg has no adapter for a bare dict or list and
# crud_* binds values through unchanged, so a lost Jsonb wrapper fails only
# against a real database. No fake-based test can observe it, which is why it is
# asserted on the source text below.
_JSONB_COLUMNS = {"bug_fix_store": ("changed_files", "tests", "revert_info")}

# Functions deliberately left on hand-written SQL, with the reason. Each uses
# count(*) OVER() for an atomic page-plus-total; splitting that into two queries
# would let the count drift from the page it describes.
_INTENTIONALLY_UNMIGRATED = {
    "wish_store": ("list_wishes_page",),
    "calendar_entry_store": ("list_calendar_entries_page",),
    "todo_store": ("list_todos_page",),
}


def _repo_path(module) -> str:
    absolute = pathlib.Path(module.__file__).resolve()
    root = pathlib.Path(__file__).resolve().parent.parent
    return str(absolute.relative_to(root))


def _head_source(path: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{path}"], capture_output=True, text=True, check=False
    ).stdout
    # A silent skip here would read as a pass, so an unresolvable path is loud.
    assert out, f"no HEAD revision found for {path!r}; the path is probably wrong"
    return out


def _public_arg_specs(source: str) -> dict[str, str]:
    return {
        node.name: ast.unparse(node.args)
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }


@pytest.mark.parametrize(("module", "entity"), _MIGRATED, ids=lambda item: getattr(item, "__name__", str(item)))
def test_descriptor_is_populated_and_valid(module, entity) -> None:
    """A store cannot be called migrated while its descriptor is empty."""
    entity.validate_descriptor()
    assert entity.COLUMNS and entity.INSERT_COLUMNS and entity.UPDATE_COLUMNS
    assert entity.ID_COLUMN in entity.COLUMNS
    assert "deleted_at" not in entity.INSERT_COLUMNS, (
        f"{entity.__name__}: a create must not be able to mark a row deleted at birth"
    )
    assert "deleted_at" not in entity.UPDATE_COLUMNS, (
        f"{entity.__name__}: soft deletion goes through crud_soft_delete, which writes "
        "the column directly and never consults UPDATE_COLUMNS"
    )
    for column in ("uuid", "created_at", "updated_at"):
        if column in set(entity.COLUMNS):
            assert column in entity.INSERT_COLUMNS, (
                f"{entity.__name__}.INSERT_COLUMNS omits {column}, which the store supplies "
                "explicitly; crud_create would reject the store's own payload"
            )


@pytest.mark.parametrize(("module", "entity"), _MIGRATED, ids=lambda item: getattr(item, "__name__", str(item)))
def test_public_signatures_survived_the_migration(module, entity) -> None:
    """The migration is internal: no caller may need an edit."""
    old = _public_arg_specs(_head_source(_repo_path(module)))
    new = _public_arg_specs(pathlib.Path(module.__file__).read_text())
    assert set(old) <= set(new), f"public functions disappeared: {sorted(set(old) - set(new))}"
    changed = {name: (old[name], new[name]) for name in old if old[name] != new[name]}
    assert changed == {}, f"public signatures changed: {changed}"


@pytest.mark.parametrize(("module", "entity"), _MIGRATED, ids=lambda item: getattr(item, "__name__", str(item)))
def test_audit_calls_stayed_in_the_store(module, entity) -> None:
    """Auditing belongs to the store, not to the entity layer it now calls."""
    head = _head_source(_repo_path(module))
    current = pathlib.Path(module.__file__).read_text()
    assert current.count("record_runtime_change(") == head.count("record_runtime_change("), (
        "the number of audit writes changed; the migration must neither drop one nor "
        "move it into the entity layer"
    )


@pytest.mark.parametrize(("module", "entity"), _MIGRATED, ids=lambda item: getattr(item, "__name__", str(item)))
def test_store_actually_delegates(module, entity) -> None:
    """The point of the migration: the store calls crud_*, not raw SQL."""
    source = pathlib.Path(module.__file__).read_text()
    used = {
        name for name in ("crud_create", "crud_get", "crud_update", "crud_soft_delete", "crud_list")
        if f"{entity.__name__}.{name}" in source
    }
    assert {"crud_create", "crud_get", "crud_update", "crud_soft_delete"} <= used, (
        f"{module.__name__} does not delegate the full CRUD set; found {sorted(used)}"
    )


@pytest.mark.parametrize(("store_name", "columns"), sorted(_JSONB_COLUMNS.items()))
def test_jsonb_columns_keep_their_wrapping(store_name, columns) -> None:
    path = f"plan_manager/storage/{store_name}.py"
    source = pathlib.Path(path).read_text()
    head = _head_source(path)
    assert source.count("Jsonb(") >= head.count("Jsonb("), (
        f"{store_name} lost Jsonb wrapping relative to HEAD "
        f"({head.count('Jsonb(')} -> {source.count('Jsonb(')})"
    )
    for column in columns:
        assert f'"{column}": {column},' not in source, (
            f"{store_name} assigns {column} unwrapped; it is a jsonb column"
        )


@pytest.mark.parametrize(("store_name", "functions"), sorted(_INTENTIONALLY_UNMIGRATED.items()))
def test_atomic_page_queries_were_not_split(store_name, functions) -> None:
    """The window-function page/total strategy must survive the migration.

    Replacing count(*) OVER() with a separate COUNT is not a refactor: the two
    queries are not atomic, so the total can describe a different row set than
    the page returned beside it.
    """
    source = pathlib.Path(f"plan_manager/storage/{store_name}.py").read_text()
    for function in functions:
        body = source.split(f"def {function}(", 1)
        assert len(body) == 2, f"{store_name} has no {function}"
        segment = body[1].split("\ndef ", 1)[0]
        assert "count(*) OVER()" in segment, (
            f"{store_name}.{function} no longer uses count(*) OVER(); the page and its "
            "total are no longer computed atomically"
        )


def test_todo_store_delegates_through_its_real_entry_points(monkeypatch) -> None:
    """Drive todo_store's own functions and assert the crud_* calls they make."""
    calls: list[str] = []
    monkeypatch.setattr(todo_store, "record_runtime_change", lambda *a, **k: None)

    row = {name: None for name in TodoItem.COLUMNS}
    row.update(
        uuid=uuid.uuid4(), title="t", description="d", kind="task", status="open",
        priority_nice=0, created_by="a", created_at=_NOW, updated_at=_NOW,
        primary_anchor_type="none",
    )
    for method in ("crud_create", "crud_get", "crud_update", "crud_soft_delete"):
        monkeypatch.setattr(
            TodoItem, method,
            classmethod(lambda cls, *a, _m=method, **k: (calls.append(_m), row)[1]),
        )
    monkeypatch.setattr(
        TodoItem, "crud_list",
        classmethod(lambda cls, *a, **k: (calls.append("crud_list"), [row])[1]),
    )

    todo_store.get_todo(object(), row["uuid"])
    todo_store.list_todos(object())
    todo_store.update_todo(object(), row["uuid"], changed_by="a", title="new")
    todo_store.resolve_todo(object(), row["uuid"], changed_by="a")
    todo_store.close_todo(object(), row["uuid"], changed_by="a")
    todo_store.soft_delete_todo(object(), row["uuid"], changed_by="a")

    for expected in ("crud_get", "crud_list", "crud_update", "crud_soft_delete"):
        assert expected in calls, f"todo_store never called {expected}"
    # resolve and close are status transitions expressed as updates, not as
    # bespoke SQL, so they must appear as crud_update calls too.
    assert calls.count("crud_update") >= 3, (
        f"expected update, resolve and close to route through crud_update; saw {calls}"
    )


def test_documented_soft_delete_opt_outs_are_intact() -> None:
    """Entities that are hard-delete-only stay that way, deliberately."""
    from plan_manager.domain.concept import Concept
    from plan_manager.domain.relation import Relation
    from plan_manager.domain.step import Step

    for entity in (Concept, Relation, Step):
        assert entity.SOFT_DELETE_COLUMN is None, (
            f"{entity.__name__} gained a soft-delete column; it is intentionally "
            "hard-delete-only and outside the batch-purge lifecycle"
        )
