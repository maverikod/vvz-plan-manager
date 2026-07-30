"""Delegation suite for the migrated overlay and agent-config stores (CR-6 G-003/T-004).

Fakes only; no live database. These tests assert that a store DELEGATES to its
entity's crud_* classmethods rather than re-implementing SQL, and that the
migration preserved the two things callers depend on: the public signature and
the audit record.
"""

from __future__ import annotations

import inspect
import pathlib
import subprocess
import uuid
from datetime import datetime, timezone
import pytest

from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.tool import Tool
from plan_manager.storage import execution_attempt_store, runtime_comment_store, tool_store

_NOW = datetime(2026, 7, 30, tzinfo=timezone.utc)

# Entities whose descriptor these stores consume, with the jsonb columns whose
# Jsonb wrapping must survive the migration. psycopg has no adapter for a bare
# dict or list, so a lost wrapper fails only against a real database — never in
# a fake-based test. That is why it is asserted structurally below.
_JSONB_COLUMNS = {
    "tool_store": ("pinned_options",),
    "execution_attempt_store": ("changed_files", "command_test_results", "resource_accounting"),
}


def _public_signatures(module) -> dict[str, str]:
    return {
        name: str(inspect.signature(obj))
        for name, obj in vars(module).items()
        if inspect.isfunction(obj) and not name.startswith("_") and obj.__module__ == module.__name__
    }


def _repo_path(module) -> str:
    """Repo-relative path of a module, for `git show HEAD:<path>`."""
    absolute = pathlib.Path(module.__file__).resolve()
    root = pathlib.Path(__file__).resolve().parent.parent
    return str(absolute.relative_to(root))


def _head_source(path: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{path}"], capture_output=True, text=True, check=False
    ).stdout
    # A silent skip here would read as a pass, so make an unresolvable path loud.
    assert out, f"no HEAD revision found for {path!r}; the path is probably wrong"
    return out


@pytest.mark.parametrize(
    "entity",
    [Tool, RuntimeComment, ExecutionAttempt],
    ids=lambda cls: cls.__name__,
)
def test_migrated_entity_descriptor_is_populated_and_valid(entity) -> None:
    """A store cannot be called migrated while its descriptor is empty."""
    entity.validate_descriptor()
    assert entity.COLUMNS, f"{entity.__name__} declares no COLUMNS"
    assert entity.INSERT_COLUMNS, f"{entity.__name__} declares no INSERT_COLUMNS"
    assert entity.ID_COLUMN in entity.COLUMNS

    columns = set(entity.COLUMNS)
    # deleted_at must never be insertable: a create may not mark a row deleted
    # at birth. It must also stay out of UPDATE_COLUMNS, because soft deletion
    # goes through crud_soft_delete, which writes the column directly.
    assert "deleted_at" not in entity.INSERT_COLUMNS
    assert "deleted_at" not in entity.UPDATE_COLUMNS
    # uuid, created_at and updated_at carry no DB default and are supplied by
    # the store, so a create must be allowed to set them.
    for column in ("uuid", "created_at", "updated_at"):
        if column in columns:
            assert column in entity.INSERT_COLUMNS, (
                f"{entity.__name__}.INSERT_COLUMNS omits {column}, which the store supplies "
                "explicitly; crud_create would reject the store's own payload"
            )


@pytest.mark.parametrize(
    "module",
    [tool_store, runtime_comment_store, execution_attempt_store],
    ids=lambda mod: mod.__name__.rsplit(".", 1)[-1],
)
def test_public_signatures_survived_the_migration(module) -> None:
    """The migration is internal: no caller may need an edit."""
    import ast

    head = _head_source(_repo_path(module))

    old = {
        node.name: ast.unparse(node.args)
        for node in ast.parse(head).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    new = {
        node.name: ast.unparse(node.args)
        for node in ast.parse(open(module.__file__).read()).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert set(old) <= set(new), f"public functions disappeared: {sorted(set(old) - set(new))}"
    changed = {name: (old[name], new[name]) for name in old if old[name] != new[name]}
    assert changed == {}, f"public signatures changed: {changed}"


@pytest.mark.parametrize(
    "module",
    [tool_store, runtime_comment_store, execution_attempt_store],
    ids=lambda mod: mod.__name__.rsplit(".", 1)[-1],
)
def test_audit_calls_stayed_in_the_store(module) -> None:
    """Auditing belongs to the store, not to the entity layer it now calls."""
    head = _head_source(_repo_path(module))
    current = open(module.__file__).read()
    assert current.count("record_runtime_change(") == head.count("record_runtime_change("), (
        "the number of audit writes changed; the migration must neither drop one "
        "nor move it into the entity layer"
    )


@pytest.mark.parametrize(
    ("store_name", "columns"),
    sorted(_JSONB_COLUMNS.items()),
)
def test_jsonb_columns_keep_their_wrapping(store_name, columns) -> None:
    """A bare dict or list reaching a jsonb bind parameter fails at runtime.

    crud_create and crud_update pass values straight through, so the wrapping
    has to happen in the store. No fake-based test can observe this, which is
    exactly why it is asserted on the source.
    """
    path = f"plan_manager/storage/{store_name}.py"
    source = open(path).read()
    head = _head_source(path)
    assert source.count("Jsonb(") >= head.count("Jsonb("), (
        f"{store_name} lost Jsonb wrapping relative to HEAD "
        f"({head.count('Jsonb(')} -> {source.count('Jsonb(')})"
    )
    assert "Jsonb" in source, f"{store_name} imports no Jsonb yet declares jsonb columns"
    for column in columns:
        assert f'"{column}": {column},' not in source, (
            f"{store_name} assigns {column} unwrapped; it is a jsonb column"
        )


def test_tool_store_delegates_to_crud(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(tool_store, "record_runtime_change", lambda *a, **k: None)

    row = {name: None for name in Tool.COLUMNS}
    row.update(
        uuid=uuid.uuid4(), name="t", server_id="s", command="c",
        pinned_options={}, created_by="a", created_at=_NOW, updated_at=_NOW,
    )
    for method in ("crud_create", "crud_get", "crud_update", "crud_soft_delete"):
        monkeypatch.setattr(
            Tool, method,
            classmethod(lambda cls, *a, _m=method, **k: (calls.append(_m), row)[1]),
        )
    monkeypatch.setattr(Tool, "crud_list", classmethod(lambda cls, *a, **k: (calls.append("crud_list"), [row])[1]))

    tool_store.create_tool(
        conn=object(), name="t", server_id="s", command="c",
        pinned_options={}, description=None, created_by="a",
    )
    tool_store.get_tool(object(), row["uuid"])
    tool_store.list_tools(object())
    tool_store.update_tool(object(), row["uuid"], changed_by="a", description="d")
    tool_store.remove_tool(object(), row["uuid"], changed_by="a")

    for expected in ("crud_create", "crud_get", "crud_list", "crud_update", "crud_soft_delete"):
        assert expected in calls, f"tool_store never called {expected}; it still hand-writes SQL"


def test_documented_append_only_gaps_are_intact() -> None:
    """The append-only stores keep their deliberate non-applicability."""
    from plan_manager.storage.command_metrics_store import CommandMetricRecord
    from plan_manager.storage.runtime_audit_store import RuntimeAuditRecord

    assert CommandMetricRecord.SOFT_DELETE_COLUMN is None
    assert CommandMetricRecord.UPDATED_AT_COLUMN is None
    with pytest.raises(Exception):
        CommandMetricRecord.crud_update(object(), uuid.uuid4(), {"mode": "x"})

    # The audit trail is immutable and leaves only through its parent cascade.
    assert RuntimeAuditRecord.SOFT_DELETE_COLUMN is None
