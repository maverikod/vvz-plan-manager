"""reference_repair command regression suite (CR-7 G-006/T-002/A-002).

Fakes only -- db_connection yields a dummy and every repair-store function
(find_dangling_references, clear_reference, delete_carrier) is monkeypatched
at the command module's namespace, matching the conventions of
tests/test_runtime_purge_batch_command.py and
tests/test_reference_inspection_command.py. Nothing here touches a database.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from mcp_proxy_adapter.core.errors import InvalidParamsError, ValidationError

from plan_manager.commands import reference_repair_command as module
from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.commands.reference_repair_command import ReferenceRepairCommand
from plan_manager.domain.entity import EntityNotSoftDeletedError, EntityReferencedError
from plan_manager.storage.errors import NotFoundError


@contextmanager
def _fake_db():
    yield object()


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)


def _run(**params: Any) -> Any:
    return asyncio.run(ReferenceRepairCommand().execute(**params))


# ---------------------------------------------------------------- schema/metadata


def test_schema_sanity() -> None:
    schema = ReferenceRepairCommand.get_schema()
    properties = schema["properties"]

    assert properties["operation"]["enum"] == ["find", "clear", "delete_carriers"]
    assert schema["required"] == ["operation"]
    assert schema["additionalProperties"] is False

    assert properties["dry_run"]["type"] == "boolean"
    assert properties["dry_run"]["default"] is True
    assert properties["entity_ids"]["items"] == {"type": "string", "format": "uuid"}
    assert properties["entity_ids"]["minItems"] == 1
    assert properties["source_ref"]["format"] == "uuid"

    assert "reference_repair" == ReferenceRepairCommand.name


def test_metadata_sanity() -> None:
    metadata = ReferenceRepairCommand.metadata()
    assert set(metadata["parameters"]) == {
        "operation", "dry_run", "source_table", "source_column",
        "source_ref", "entity_ids", "changed_by",
    }
    assert metadata["parameters"]["operation"]["required"] is True
    for optional in ("dry_run", "source_table", "source_column", "source_ref", "entity_ids", "changed_by"):
        assert metadata["parameters"][optional]["required"] is False

    error_cases = metadata["error_cases"]
    assert set(error_cases) == {"REFERENCE_NOT_CLEARABLE", "RUNTIME_VALIDATION_ERROR", "DELETE_BLOCKED"}
    for code, case in error_cases.items():
        assert code in DOMAIN_CODES, f"{code} is advertised but not a registered domain code"
        assert "description" in case and "solution" in case, f"{code} breaks the error_cases shape"

    for key in (
        "name", "version", "description", "category", "author", "email",
        "detailed_description", "parameters", "return_value", "usage_examples",
        "error_cases", "best_practices",
    ):
        assert key in metadata, f"metadata missing required key {key}"


def test_command_is_registered_and_mutating() -> None:
    assert "reference_repair" in INVENTORY
    assert "reference_repair" in MUTATING, (
        "clear and delete_carriers(dry_run=false) write; the command as a "
        "whole must stay classified mutating, matching runtime_purge_batch"
    )


# ---------------------------------------------------------------- validate_params


def test_validate_params_rejects_unknown_operation() -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        ReferenceRepairCommand().validate_params({"operation": "wipe"})


def test_validate_params_requires_operation() -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        ReferenceRepairCommand().validate_params({})


def test_validate_params_find_needs_nothing_else() -> None:
    params = ReferenceRepairCommand().validate_params({"operation": "find"})
    assert params == {"operation": "find"}


def test_validate_params_clear_requires_all_three_fields() -> None:
    with pytest.raises(InvalidParamsError) as excinfo:
        ReferenceRepairCommand().validate_params({"operation": "clear", "source_table": "todo_item"})
    assert "source_column" in str(excinfo.value)
    assert "source_ref" in str(excinfo.value)


def test_validate_params_clear_rejects_a_malformed_source_ref() -> None:
    with pytest.raises(InvalidParamsError):
        ReferenceRepairCommand().validate_params(
            {
                "operation": "clear",
                "source_table": "todo_item",
                "source_column": "anchor_plan_uuid",
                "source_ref": "not-a-uuid",
            }
        )


def test_validate_params_clear_accepts_well_formed_params() -> None:
    params = ReferenceRepairCommand().validate_params(
        {
            "operation": "clear",
            "source_table": "todo_item",
            "source_column": "anchor_plan_uuid",
            "source_ref": str(uuid.uuid4()),
        }
    )
    assert params["operation"] == "clear"


def test_validate_params_delete_carriers_requires_non_empty_entity_ids() -> None:
    with pytest.raises((InvalidParamsError, ValidationError)):
        ReferenceRepairCommand().validate_params({"operation": "delete_carriers"})


def test_validate_params_delete_carriers_rejects_a_malformed_entity_id() -> None:
    with pytest.raises(InvalidParamsError):
        ReferenceRepairCommand().validate_params(
            {"operation": "delete_carriers", "entity_ids": ["not-a-uuid"]}
        )


def test_validate_params_delete_carriers_dry_run_true_needs_no_changed_by() -> None:
    params = ReferenceRepairCommand().validate_params(
        {"operation": "delete_carriers", "entity_ids": [str(uuid.uuid4())]}
    )
    assert "changed_by" not in params


def test_validate_params_delete_carriers_live_requires_changed_by() -> None:
    with pytest.raises(InvalidParamsError) as excinfo:
        ReferenceRepairCommand().validate_params(
            {"operation": "delete_carriers", "entity_ids": [str(uuid.uuid4())], "dry_run": False}
        )
    assert "changed_by" in str(excinfo.value)


def test_validate_params_delete_carriers_live_accepts_changed_by() -> None:
    params = ReferenceRepairCommand().validate_params(
        {
            "operation": "delete_carriers",
            "entity_ids": [str(uuid.uuid4())],
            "dry_run": False,
            "changed_by": "tester",
        }
    )
    assert params["changed_by"] == "tester"


# ---------------------------------------------------------------- execute: find


def test_execute_find_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    source_ref, missing_target = uuid.uuid4(), uuid.uuid4()
    finding = {
        "source_table": "todo_item",
        "source_column": "anchor_plan_uuid",
        "source_ref": source_ref,
        "property_name": "anchor_plan_uuid",
        "missing_target": missing_target,
        "target_table": "plan",
        "nullability": "nullable",
    }
    monkeypatch.setattr(module, "find_dangling_references", lambda conn: [finding])

    result = _run(operation="find")

    assert result.data == {
        "operation": "find",
        "findings": [
            {
                "source_table": "todo_item",
                "source_column": "anchor_plan_uuid",
                "source_ref": str(source_ref),
                "property_name": "anchor_plan_uuid",
                "missing_target": str(missing_target),
                "target_table": "plan",
                "nullability": "nullable",
            }
        ],
        "total": 1,
    }


def test_execute_find_empty_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "find_dangling_references", lambda conn: [])
    result = _run(operation="find")
    assert result.data == {"operation": "find", "findings": [], "total": 0}


# ---------------------------------------------------------------- execute: clear


def test_execute_clear_names_the_columns_it_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    source_ref = uuid.uuid4()
    forwarded: list[dict[str, Any]] = []

    def _fake_clear(conn: Any, *, source_table: str, source_column: str, source_ref: uuid.UUID) -> dict[str, Any]:
        forwarded.append({"source_table": source_table, "source_column": source_column, "source_ref": source_ref})
        return {
            "source_table": source_table,
            "source_column": source_column,
            "source_ref": source_ref,
            "cleared": True,
        }

    monkeypatch.setattr(module, "clear_reference", _fake_clear)

    result = _run(
        operation="clear",
        source_table="todo_item",
        source_column="anchor_plan_uuid",
        source_ref=str(source_ref),
    )

    assert forwarded == [
        {"source_table": "todo_item", "source_column": "anchor_plan_uuid", "source_ref": source_ref}
    ]
    assert result.data == {
        "operation": "clear",
        "source_table": "todo_item",
        "source_column": "anchor_plan_uuid",
        "source_ref": str(source_ref),
        "cleared": True,
    }


def test_execute_clear_maps_a_permission_error_to_reference_not_clearable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _refuse(conn: Any, *, source_table: str, source_column: str, source_ref: uuid.UUID) -> dict[str, Any]:
        raise PermissionError(
            f"{source_table}.{source_column} is not_nullable; clear refused "
            "(only a statically-nullable column may be cleared)"
        )

    monkeypatch.setattr(module, "clear_reference", _refuse)
    monkeypatch.setattr(module, "nullability_for", lambda table, column: "not_nullable")

    result = _run(
        operation="clear",
        source_table="execution_attempt",
        source_column="plan_uuid",
        source_ref=str(uuid.uuid4()),
    )

    assert result.details["domain_code"] == "REFERENCE_NOT_CLEARABLE"
    assert result.details["nullability"] == "not_nullable"
    assert "not_nullable" in result.message


def test_execute_clear_maps_an_unknown_nullability_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(conn: Any, *, source_table: str, source_column: str, source_ref: uuid.UUID) -> dict[str, Any]:
        raise PermissionError(f"{source_table}.{source_column} is unknown; clear refused")

    monkeypatch.setattr(module, "clear_reference", _refuse)
    monkeypatch.setattr(module, "nullability_for", lambda table, column: "unknown")

    result = _run(
        operation="clear",
        source_table="paragraph",
        source_column="plan_uuid",
        source_ref=str(uuid.uuid4()),
    )

    assert result.details["domain_code"] == "REFERENCE_NOT_CLEARABLE"
    assert result.details["nullability"] == "unknown"


def test_execute_clear_maps_an_uncatalogued_column_to_runtime_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_key_error(conn: Any, *, source_table: str, source_column: str, source_ref: uuid.UUID) -> dict[str, Any]:
        raise KeyError(f"not a catalogued reference: {source_table}.{source_column}")

    monkeypatch.setattr(module, "clear_reference", _raise_key_error)

    result = _run(
        operation="clear",
        source_table="todo_item",
        source_column="not_a_real_column",
        source_ref=str(uuid.uuid4()),
    )

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"
    assert "not a catalogued reference" in result.message


# ---------------------------------------------------------------- execute: delete_carriers


def test_execute_delete_carriers_dry_run_default_reports_would_remove_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier_id = uuid.uuid4()
    forwarded: list[dict[str, Any]] = []

    def _fake_delete_carrier(conn: Any, ids: Any, *, dry_run: bool, changed_by: str) -> dict[str, Any]:
        forwarded.append({"ids": ids, "dry_run": dry_run, "changed_by": changed_by})
        return {
            "dry_run": True,
            "would_remove": [carrier_id],
            "blocked_by": [],
            "unresolved": [],
            "admissible": True,
        }

    monkeypatch.setattr(module, "delete_carrier", _fake_delete_carrier)

    result = _run(operation="delete_carriers", entity_ids=[str(carrier_id)])

    assert forwarded == [{"ids": [carrier_id], "dry_run": True, "changed_by": "system"}]
    assert result.data == {
        "operation": "delete_carriers",
        "dry_run": True,
        "would_remove": [str(carrier_id)],
        "blocked_by": [],
        "unresolved": [],
        "admissible": True,
    }


def test_execute_delete_carriers_dry_run_serializes_blocked_by_triples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    carrier_id, referrer_id, field_ref = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    monkeypatch.setattr(
        module,
        "delete_carrier",
        lambda conn, ids, *, dry_run, changed_by: {
            "dry_run": True,
            "would_remove": [carrier_id],
            "blocked_by": [{"source_ref": referrer_id, "target_ref": carrier_id, "field_ref": field_ref}],
            "unresolved": [],
            "admissible": False,
        },
    )

    result = _run(operation="delete_carriers", entity_ids=[str(carrier_id)])

    assert result.data["admissible"] is False
    assert result.data["blocked_by"] == [
        {"source_ref": str(referrer_id), "target_ref": str(carrier_id), "field_ref": str(field_ref)}
    ]


def test_execute_delete_carriers_dry_run_false_acts_via_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    carrier_id = uuid.uuid4()
    forwarded: list[dict[str, Any]] = []

    def _fake_delete_carrier(conn: Any, ids: Any, *, dry_run: bool, changed_by: str) -> dict[str, Any]:
        forwarded.append({"ids": ids, "dry_run": dry_run, "changed_by": changed_by})
        return {"dry_run": False, "removed": [carrier_id]}

    monkeypatch.setattr(module, "delete_carrier", _fake_delete_carrier)

    result = _run(
        operation="delete_carriers",
        entity_ids=[str(carrier_id)],
        dry_run=False,
        changed_by="repair-bot",
    )

    assert forwarded == [{"ids": [carrier_id], "dry_run": False, "changed_by": "repair-bot"}]
    assert result.data == {
        "operation": "delete_carriers",
        "dry_run": False,
        "removed": [str(carrier_id)],
    }


def test_execute_delete_carriers_maps_a_not_found_identifier_to_runtime_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = uuid.uuid4()

    def _fake_delete_carrier(conn: Any, ids: Any, *, dry_run: bool, changed_by: str) -> dict[str, Any]:
        raise NotFoundError(f"entity identity not found: {missing}")

    monkeypatch.setattr(module, "delete_carrier", _fake_delete_carrier)

    result = _run(
        operation="delete_carriers", entity_ids=[str(missing)], dry_run=False, changed_by="tester"
    )

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_execute_delete_carriers_maps_an_unmarked_identifier_to_runtime_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = uuid.uuid4()

    def _fake_delete_carrier(conn: Any, ids: Any, *, dry_run: bool, changed_by: str) -> dict[str, Any]:
        raise EntityNotSoftDeletedError("todo", live)

    monkeypatch.setattr(module, "delete_carrier", _fake_delete_carrier)

    result = _run(
        operation="delete_carriers", entity_ids=[str(live)], dry_run=False, changed_by="tester"
    )

    assert result.details["domain_code"] == "RUNTIME_VALIDATION_ERROR"


def test_execute_delete_carriers_live_refusal_maps_to_delete_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_set_member, blocking_referrer = uuid.uuid4(), uuid.uuid4()

    def _fake_delete_carrier(conn: Any, ids: Any, *, dry_run: bool, changed_by: str) -> dict[str, Any]:
        raise EntityReferencedError(
            "hard_delete_marked_set",
            [working_set_member],
            [
                {
                    "table": None,
                    "column": "field",
                    "referrer_id": blocking_referrer,
                    "referrer_kind": "relation_index",
                }
            ],
        )

    monkeypatch.setattr(module, "delete_carrier", _fake_delete_carrier)

    result = _run(
        operation="delete_carriers",
        entity_ids=[str(working_set_member)],
        dry_run=False,
        changed_by="tester",
    )

    assert result.details["domain_code"] == "DELETE_BLOCKED"
