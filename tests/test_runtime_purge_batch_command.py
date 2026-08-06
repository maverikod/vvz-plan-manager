"""runtime_purge_batch command suite.

CR-6 G-004/T-003 originally shipped this command driving
entity.purge_soft_deleted_batch (per entity type, report-one-and-continue).
CR-7 G-006/T-001/A-002 reverses the command onto the set-wise engine landed by
sibling step A-001 (storage.runtime_hard_delete.hard_delete_marked_set): every
test below that exercises the COMMAND (schema, metadata, validate_params,
execute) is rewritten for that reversal, each edit commented "G-006/T-001/A-002".

The lower A-001(CR-6) suite at the bottom -- test_purge_batch_* -- exercises
entity.purge_soft_deleted_batch and TodoItem.crud_purge_soft_deleted_batch
directly, not through the command. That mechanism is untouched by this step
(this command no longer calls it, but the function itself still exists,
unmodified, in domain/entity.py) and those tests are left as accurate
coverage of it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from mcp_proxy_adapter.core.errors import InvalidParamsError, ValidationError

from plan_manager.commands import runtime_purge_batch_command as module
from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.commands.runtime_purge_batch_command import RuntimePurgeBatchCommand
from plan_manager.domain import entity as entity_module
from plan_manager.domain.entity import (
    EntityNotSoftDeletedError,
    EntityReferencedError,
    purge_soft_deleted_batch,
)
from plan_manager.domain.todo import TodoItem
from plan_manager.storage.errors import NotFoundError


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
    # G-006/T-001/A-002: limit is gone (the whole-set-or-nothing contract has
    # no partial-batch concept to bound); identifiers is the new, optional,
    # scoping parameter; entity_type survives only as an optional,
    # non-scoping pre-flight sanity check (see test_metadata_sanity).
    schema = RuntimePurgeBatchCommand.get_schema()
    properties = schema["properties"]

    assert "limit" not in properties

    identifiers = properties["identifiers"]
    assert identifiers["type"] == "array"
    assert identifiers["items"] == {"type": "string", "format": "uuid"}

    assert "entity_type" in properties
    assert "runtime_purge_batch" == RuntimePurgeBatchCommand.name  # sanity: same command

    assert properties["changed_by"]["type"] == "string"
    assert set(schema["required"]) == {"changed_by"}
    assert schema["additionalProperties"] is False


def test_metadata_sanity() -> None:
    # G-006/T-001/A-002: the parameter set, return shape and advertised error
    # codes all follow the reversal onto hard_delete_marked_set.
    metadata = RuntimePurgeBatchCommand.metadata()
    assert set(metadata["parameters"]) == {"identifiers", "entity_type", "changed_by"}
    assert metadata["parameters"]["identifiers"]["required"] is False
    assert metadata["parameters"]["entity_type"]["required"] is False
    assert metadata["parameters"]["changed_by"]["required"] is True

    assert "removed" in metadata["return_value"]["success"]["data"]
    assert "removed_count" in metadata["return_value"]["success"]["data"]
    # The old per-row shape must not survive into the documented contract.
    assert "deleted" not in metadata["return_value"]["success"]["data"]
    assert "refused" not in metadata["return_value"]["success"]["data"]

    error_cases = metadata["error_cases"]
    assert "DELETE_BLOCKED" in error_cases, (
        "the whole-operation refusal must be advertised"
    )
    assert "RUNTIME_VALIDATION_ERROR" in error_cases
    assert "ENTITY_NOT_PURGEABLE" in error_cases, (
        "entity_type survives as an optional pre-flight check, so its refusal "
        "code must stay reachable and advertised"
    )
    for code, case in error_cases.items():
        assert code in DOMAIN_CODES, f"{code} is advertised but not a registered domain code"
        # Repository convention: description plus solution, never 'fix' or 'hint'.
        assert "description" in case and "solution" in case, f"{code} breaks the error_cases shape"
    assert any(
        "idempotent" in practice for practice in metadata["best_practices"]
    ), "the idempotence of the default (identifiers-omitted) call must be documented"


def test_command_is_registered_as_mutating() -> None:
    assert "runtime_purge_batch" in INVENTORY
    assert "runtime_purge_batch" in MUTATING


# ---------------------------------------------------------------- validate_params


def test_validate_params_refuses_a_non_array_identifiers(monkeypatch: pytest.MonkeyPatch) -> None:
    # G-006/T-001/A-002: identifiers replaces entity_type as the scoping param.
    with pytest.raises((InvalidParamsError, ValidationError)):
        RuntimePurgeBatchCommand().validate_params(
            {"identifiers": "not-an-array", "changed_by": "tester"}
        )


def test_validate_params_refuses_a_malformed_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises((InvalidParamsError, ValidationError)) as excinfo:
        RuntimePurgeBatchCommand().validate_params(
            {"identifiers": ["not-a-uuid"], "changed_by": "tester"}
        )
    assert "not-a-uuid" in str(excinfo.value)


def test_validate_params_accepts_a_well_formed_identifier_list() -> None:
    params = RuntimePurgeBatchCommand().validate_params(
        {"identifiers": [str(uuid.uuid4()), str(uuid.uuid4())], "changed_by": "tester"}
    )
    assert len(params["identifiers"]) == 2


def test_validate_params_refuses_an_empty_actor() -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        RuntimePurgeBatchCommand().validate_params({"changed_by": "   "})


@pytest.mark.parametrize("entity_type", ["concept", "relation", "step"])
def test_validate_params_refuses_a_non_purgeable_entity_type(entity_type: str) -> None:
    # G-006/T-001/A-002: entity_type survives only as an optional pre-flight
    # sanity check, not a scope filter -- but the check itself is unchanged.
    with pytest.raises((InvalidParamsError, ValidationError)) as excinfo:
        RuntimePurgeBatchCommand().validate_params(
            {"entity_type": entity_type, "changed_by": "tester"}
        )
    assert "SOFT_DELETE_COLUMN=None" in str(excinfo.value)


def test_execute_maps_a_non_purgeable_entity_type_to_a_domain_code() -> None:
    """execute() re-checks entity_type independently of validate_params.

    Same reasoning this command has always used for this check: execute() is
    a public entry point internal callers and tests invoke directly, and a
    DomainCommandError raised from validate_params would escape the adapter's
    run() unmapped.
    """
    result = _run(entity_type="concept", changed_by="tester")
    assert result.details["domain_code"] == "ENTITY_NOT_PURGEABLE"


# ---------------------------------------------------------------- execute


def test_execute_default_call_forwards_none_and_reports_the_fixed_point_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # G-006/T-001/A-002 default-set coverage: identifiers omitted must forward
    # entity_ids=None, which is hard_delete_marked_set's own "every marked
    # entity across every type" default -- not a command-level re-derivation.
    first, second = uuid.uuid4(), uuid.uuid4()
    forwarded: list[dict[str, Any]] = []

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        forwarded.append({"entity_ids": entity_ids, "changed_by": changed_by})
        return {"removed": [first, second]}

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)

    result = _run(changed_by="sweeper")

    assert forwarded == [{"entity_ids": None, "changed_by": "sweeper"}]
    assert result.data == {
        "removed": [str(first), str(second)],
        "removed_count": 2,
    }


def test_execute_forwards_explicit_identifiers_as_uuids(monkeypatch: pytest.MonkeyPatch) -> None:
    given = uuid.uuid4()
    forwarded: list[dict[str, Any]] = []

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        forwarded.append({"entity_ids": entity_ids, "changed_by": changed_by})
        return {"removed": [given]}

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)

    result = _run(identifiers=[str(given)], changed_by="orchestrator")

    assert forwarded == [{"entity_ids": [given], "changed_by": "orchestrator"}]
    assert result.data == {"removed": [str(given)], "removed_count": 1}


def test_execute_idempotent_default_with_nothing_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module, "hard_delete_marked_set", lambda conn, entity_ids, *, changed_by: {"removed": []}
    )

    result = _run(changed_by="sweeper")

    assert result.data == {"removed": [], "removed_count": 0}


def test_execute_writes_no_audit_of_its_own(
    monkeypatch: pytest.MonkeyPatch, audit_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        module,
        "hard_delete_marked_set",
        lambda conn, entity_ids, *, changed_by: {"removed": [uuid.uuid4(), uuid.uuid4()]},
    )

    _run(changed_by="tester")

    assert audit_calls == [], (
        "the command wrote its own audit record; the hard-delete guard beneath the "
        "engine is the single writer, so this would audit every removed row twice"
    )


def test_execute_maps_an_unregistered_explicit_identifier_to_runtime_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # G-006/T-001/A-002: an explicit id the identity registry has never seen.
    missing = uuid.uuid4()

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        raise NotFoundError(f"entity identity not found: {missing}")

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)

    result = _run(identifiers=[str(missing)], changed_by="tester")

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"
    assert str(missing) in result.message


def test_execute_maps_an_unmarked_explicit_identifier_to_runtime_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # G-006/T-001/A-002: an explicit id that exists but is not (yet) marked --
    # only an already-marked row may seed the fixed point.
    live = uuid.uuid4()

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        raise EntityNotSoftDeletedError("todo", live)

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)

    result = _run(identifiers=[str(live)], changed_by="tester")

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_execute_refusal_names_every_blocking_referrer_and_removes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # G-006/T-001/A-002 refusal-path coverage: this is the frozen step's
    # central contract change. The mechanism's EntityReferencedError is
    # mapped into a WHOLE-operation DELETE_BLOCKED refusal that names every
    # external unmarked referrer by entity_type+id, and the response makes
    # explicit that nothing was removed -- there is no partial "deleted" list
    # any more, unlike the old report-one-and-continue shape.
    working_set_member = uuid.uuid4()
    blocking_referrer = uuid.uuid4()
    field_ref = uuid.uuid4()

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        raise EntityReferencedError(
            "hard_delete_marked_set",
            [working_set_member],
            [
                {
                    "table": None,
                    "column": field_ref,
                    "referrer_id": blocking_referrer,
                    "referrer_kind": "relation_index",
                }
            ],
        )

    def _fake_resolver(conn: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        assert list(ids) == [blocking_referrer]
        return {blocking_referrer: {"entity_type": "bug", "table_name": "bug_report"}}

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)
    monkeypatch.setattr(module, "resolve_entity_identities_batch", _fake_resolver)

    result = _run(identifiers=[str(working_set_member)], changed_by="tester")

    assert result.details["domain_code"] == "DELETE_BLOCKED"
    assert result.details["blocking_referrers"] == [
        {"entity_type": "bug", "id": str(blocking_referrer), "field_ref": str(field_ref)}
    ]
    # Nothing removed is stated explicitly, not merely implied by absence.
    assert result.details["removed"] == []
    # The referrer is named in the human-readable message too, not only tucked
    # away in details.
    assert "bug" in result.message and str(blocking_referrer) in result.message


def test_execute_refusal_reports_unresolvable_referrer_entity_type_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocking referrer id the identity registry cannot resolve is still named by id."""
    blocking_referrer = uuid.uuid4()

    def _fake_engine(conn: Any, entity_ids: Any, *, changed_by: str) -> dict[str, Any]:
        raise EntityReferencedError(
            "hard_delete_marked_set",
            [],
            [
                {
                    "table": None,
                    "column": uuid.uuid4(),
                    "referrer_id": blocking_referrer,
                    "referrer_kind": "relation_index",
                }
            ],
        )

    monkeypatch.setattr(module, "hard_delete_marked_set", _fake_engine)
    monkeypatch.setattr(module, "resolve_entity_identities_batch", lambda conn, ids: {})

    result = _run(changed_by="tester")

    assert result.details["blocking_referrers"][0]["entity_type"] is None
    assert result.details["blocking_referrers"][0]["id"] == str(blocking_referrer)


# ------------------------------------------------- CR-6 A-001: actor reaches the guard
#
# Unchanged by G-006/T-001/A-002: this exercises entity.purge_soft_deleted_batch
# and TodoItem.crud_purge_soft_deleted_batch directly, not through the command
# (see the module docstring). That mechanism is untouched by this step.


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
