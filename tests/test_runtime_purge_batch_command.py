"""runtime_purge_batch command and batch-purge attribution suite (CR-6 G-004/T-003).

Fakes and mocks only — no live database. Covers both A-001 (the actor threaded
through purge_soft_deleted_batch into the guard, with no second audit write) and
A-002/A-003 (the command, its schema, and its registration).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from mcp_proxy_adapter.core.errors import InvalidParamsError, ValidationError

from plan_manager.commands import runtime_purge_batch_command as module
from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.commands.runtime_purge_batch_command import RuntimePurgeBatchCommand
from plan_manager.domain import entity as entity_module
from plan_manager.domain.entity import EntityReferencedError, purge_soft_deleted_batch
from plan_manager.domain.todo import TodoItem
from plan_manager.storage import reference_catalog

_NON_PURGEABLE = ["concept", "relation", "step"]


@contextmanager
def _fake_db():
    yield object()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)


@pytest.fixture()
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record every audit write reachable from the batch-purge path."""
    recorded: list[dict[str, Any]] = []
    from plan_manager.storage import runtime_audit_store

    monkeypatch.setattr(
        runtime_audit_store,
        "record_runtime_change",
        lambda conn, **kwargs: recorded.append(kwargs),
    )
    monkeypatch.setattr(
        module, "record_runtime_change", lambda conn, **kwargs: recorded.append(kwargs),
        raising=False,
    )
    return recorded


def _run(**params: Any) -> Any:
    return asyncio.run(RuntimePurgeBatchCommand().execute(**params))


# ---------------------------------------------------------------- schema/metadata


def test_schema_sanity() -> None:
    schema = RuntimePurgeBatchCommand.get_schema()
    properties = schema["properties"]

    enum = properties["entity_type"]["enum"]
    assert enum, "the entity_type enum is empty"
    for excluded in _NON_PURGEABLE:
        assert excluded not in enum, (
            f"{excluded} declares SOFT_DELETE_COLUMN=None and must not be offered for purge"
        )
    # The value is the ENTITY_TYPE, never the table name.
    assert "comment" in enum and "runtime_comment" not in enum
    assert "todo" in enum and "todo_item" not in enum

    limit = properties["limit"]
    assert limit["type"] == "integer"
    assert limit["minimum"] == 1
    assert limit["maximum"] == 10000
    assert limit["default"] == 1000

    assert properties["changed_by"]["type"] == "string"
    assert set(schema["required"]) == {"entity_type", "changed_by"}
    assert schema["additionalProperties"] is False


def test_metadata_sanity() -> None:
    metadata = RuntimePurgeBatchCommand.metadata()
    assert set(metadata["parameters"]) == {"entity_type", "changed_by", "limit"}
    assert "deleted" in metadata["return_value"]["success"]["data"]
    assert "refused" in metadata["return_value"]["success"]["data"]

    error_cases = metadata["error_cases"]
    assert "ENTITY_NOT_PURGEABLE" in error_cases, (
        "the non-soft-delete refusal must be advertised"
    )
    assert "SOFT_DELETE_COLUMN=None" in error_cases["ENTITY_NOT_PURGEABLE"]["description"]
    for code, case in error_cases.items():
        assert code in DOMAIN_CODES, f"{code} is advertised but not a registered domain code"
        # Repository convention: description plus solution, never 'fix' or 'hint'.
        assert "description" in case and "solution" in case, f"{code} breaks the error_cases shape"
    assert any(
        "idempotent" in practice for practice in metadata["best_practices"]
    ), "the idempotence of a repeated batch purge must be documented"


def test_command_is_registered_as_mutating() -> None:
    assert "runtime_purge_batch" in INVENTORY
    assert "runtime_purge_batch" in MUTATING


# ---------------------------------------------------------------- validate_params


@pytest.mark.parametrize("entity_type", _NON_PURGEABLE)
def test_validate_params_refuses_unsupported_entity_type(entity_type: str) -> None:
    with pytest.raises((InvalidParamsError, ValidationError)) as excinfo:
        RuntimePurgeBatchCommand().validate_params(
            {"entity_type": entity_type, "changed_by": "tester"}
        )
    # The generic enum rejection would never say why; the specific reason must
    # reach the caller.
    assert "SOFT_DELETE_COLUMN=None" in str(excinfo.value)


@pytest.mark.parametrize("limit", [0, 10001])
def test_validate_params_bounds_the_limit(limit: int) -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        RuntimePurgeBatchCommand().validate_params(
            {"entity_type": "todo", "changed_by": "tester", "limit": limit}
        )


def test_validate_params_refuses_an_empty_actor() -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        RuntimePurgeBatchCommand().validate_params(
            {"entity_type": "todo", "changed_by": "   "}
        )


# ---------------------------------------------------------------- resolution


@pytest.mark.parametrize("entity_type", ["comment", "todo"])
def test_entity_type_resolved_through_shared_helper(
    monkeypatch: pytest.MonkeyPatch, entity_type: str
) -> None:
    """The command must not carry a private type -> class mapping.

    Two independent resolvers would drift and answer differently for the same
    entity type, which is exactly the class of defect bugs e52daeab and 113a7888
    came from.
    """
    resolver = MagicMock(return_value=_purging_class({"deleted": [], "refused": []}))
    monkeypatch.setattr(module, "resolve_entity_class", resolver)

    _run(entity_type=entity_type, changed_by="tester")

    assert resolver.call_args_list, "the shared resolver was never called"
    # The ENTITY_TYPE spelling must reach the resolver untouched — not silently
    # rewritten into a table name on the way.
    assert resolver.call_args_list[0].args[0] == entity_type


def test_shared_resolver_is_the_catalog_helper() -> None:
    """The name the command imports is the catalog's, not a local copy."""
    assert module.resolve_entity_class is reference_catalog.resolve_entity_class


# ---------------------------------------------------------------- execute


def _purging_class(outcome: dict[str, Any], recorder: list[dict[str, Any]] | None = None) -> type:
    """A stand-in entity class whose batch purge returns a canned outcome."""

    class _Purgeable:
        SOFT_DELETE_COLUMN = "deleted_at"

        @classmethod
        def crud_purge_soft_deleted_batch(cls, conn: Any, **kwargs: Any) -> dict[str, Any]:
            if recorder is not None:
                recorder.append(kwargs)
            return outcome

    return _Purgeable


def test_execute_purge_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    forwarded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        module,
        "resolve_entity_class",
        lambda entity_type: _purging_class(
            {"deleted": [{"uuid": str(first)}, {"uuid": str(second)}], "refused": []}, forwarded
        ),
    )

    result = _run(entity_type="todo", changed_by="tester", limit=50)

    assert result.data["entity_type"] == "todo"
    assert result.data["deleted"] == [{"uuid": str(first)}, {"uuid": str(second)}]
    assert result.data["refused"] == []
    assert forwarded == [{"limit": 50, "changed_by": "tester"}]


def test_execute_refused_by_references(monkeypatch: pytest.MonkeyPatch) -> None:
    refusal = {"id": {"uuid": str(uuid.uuid4())}, "references": {"execution_attempt.todo_uuid": 2}}
    monkeypatch.setattr(
        module,
        "resolve_entity_class",
        lambda entity_type: _purging_class({"deleted": [], "refused": [refusal]}),
    )

    result = _run(entity_type="todo", changed_by="tester")

    # Verbatim: a refusal names the referring column, which is the only thing
    # that tells a caller what to detach before the next run.
    assert result.data["refused"] == [refusal]
    assert result.data["deleted"] == []


def test_execute_writes_no_audit_of_its_own(
    monkeypatch: pytest.MonkeyPatch, audit_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        module,
        "resolve_entity_class",
        lambda entity_type: _purging_class(
            {"deleted": [{"uuid": "a"}, {"uuid": "b"}], "refused": []}
        ),
    )

    _run(entity_type="todo", changed_by="tester")

    assert audit_calls == [], (
        "the command wrote its own audit record; the hard-delete guard beneath it is "
        "the single writer, so this would audit every purged row twice"
    )


def test_execute_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "resolve_entity_class",
        lambda entity_type: _purging_class({"deleted": [], "refused": []}),
    )

    result = _run(entity_type="todo", changed_by="tester")

    assert result.data["deleted"] == []
    assert result.data["refused"] == []


def test_limit_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded: list[dict[str, Any]] = []
    monkeypatch.setattr(
        module,
        "resolve_entity_class",
        lambda entity_type: _purging_class({"deleted": [], "refused": []}, forwarded),
    )

    _run(entity_type="todo", changed_by="tester", limit=7)
    assert forwarded[0]["limit"] == 7

    _run(entity_type="todo", changed_by="tester")
    assert forwarded[1]["limit"] == 1000, "the documented default must be the one applied"


def test_execute_maps_a_non_purgeable_type_to_a_domain_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execute() is a public entry point, so it guards independently.

    A DomainCommandError raised from validate_params would escape the adapter's
    run() unmapped, so this is the path that produces the documented code.
    """

    class _NotPurgeable:
        SOFT_DELETE_COLUMN = None

    monkeypatch.setattr(module, "resolve_entity_class", lambda entity_type: _NotPurgeable)

    result = _run(entity_type="concept", changed_by="tester")

    assert result.details["domain_code"] == "ENTITY_NOT_PURGEABLE"


# ------------------------------------------------- A-001: actor reaches the guard


class _Column:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = list(rows)
        self.description = (_Column("uuid"),)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Answers the batch's id SELECT, then nothing else."""

    def __init__(self, ids: list[uuid.UUID]) -> None:
        self._ids = ids
        self.statements: list[str] = []

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = query.as_string(None) if hasattr(query, "as_string") else str(query)
        self.statements.append(text)
        if text.startswith("SELECT") and "IS NOT NULL" in text:
            return _FakeCursor([(entity_id,) for entity_id in self._ids])
        return _FakeCursor([])


def test_purge_batch_signature_defaults_to_the_batch_actor() -> None:
    import inspect

    for function in (purge_soft_deleted_batch, TodoItem.crud_purge_soft_deleted_batch):
        parameter = inspect.signature(function).parameters["changed_by"]
        assert parameter.default == "system:purge_batch", (
            f"{function} must default the batch actor so an unattributed purge is still "
            "distinguishable from an ordinary system deletion"
        )
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_purge_batch_forwards_the_actor_into_each_hard_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [uuid.uuid4(), uuid.uuid4()]
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        entity_module,
        "hard_delete_entity",
        lambda entity_cls, conn, entity_id, **kwargs: (
            seen.append({"entity_id": entity_id, **kwargs}) or {"uuid": str(entity_id)}
        ),
    )

    outcome = purge_soft_deleted_batch(
        _FakeConn(ids), TodoItem, limit=10, changed_by="tester:batch"
    )

    assert [call["changed_by"] for call in seen] == ["tester:batch", "tester:batch"]
    assert len(outcome["deleted"]) == 2
    assert outcome["refused"] == []


def test_purge_batch_writes_no_audit_of_its_own(
    monkeypatch: pytest.MonkeyPatch, audit_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        entity_module,
        "hard_delete_entity",
        lambda entity_cls, conn, entity_id, **kwargs: {"uuid": str(entity_id)},
    )

    purge_soft_deleted_batch(_FakeConn([uuid.uuid4()]), TodoItem, changed_by="tester")

    # The guard is stubbed out here, so anything recorded came from the batch
    # function itself — which would double every purged row's audit trail.
    assert audit_calls == []


def test_purge_batch_refusal_shape_is_preserved_and_json_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    blocked = uuid.uuid4()

    def _refuse(entity_cls: type, conn: Any, entity_id: Any, **kwargs: Any) -> None:
        raise EntityReferencedError("todo", entity_id, {"execution_attempt.todo_uuid": 1})

    monkeypatch.setattr(entity_module, "hard_delete_entity", _refuse)

    outcome = purge_soft_deleted_batch(_FakeConn([blocked]), TodoItem, changed_by="tester")

    assert set(outcome) == {"deleted", "refused"}
    assert outcome["deleted"] == []
    assert outcome["refused"] == [
        {"id": {"uuid": str(blocked)}, "references": {"execution_attempt.todo_uuid": 1}}
    ]
    # Every caller serializes this structure; an unconverted uuid would raise
    # at the boundary rather than here.
    assert json.loads(json.dumps(outcome)) == outcome
