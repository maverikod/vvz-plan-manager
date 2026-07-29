"""Regression suite for the project_uuid_reserve MCP command (CR-6 G-002)."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError, ValidationError

from plan_manager.commands import project_uuid_reserve_command as mod
from plan_manager.commands.project_uuid_reserve_command import ProjectUuidReserveCommand
from plan_manager.storage.errors import DuplicateNameError, NotFoundError


@contextmanager
def _fake_db():
    yield object()


def _run(**kwargs):
    return asyncio.run(ProjectUuidReserveCommand().execute(**kwargs))


class _AuditRecorder:
    """Records every record_runtime_change call the command makes."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)

    @property
    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]


@pytest.fixture
def audit(monkeypatch):
    recorder = _AuditRecorder()
    monkeypatch.setattr(mod, "db_connection", _fake_db)
    monkeypatch.setattr(mod, "record_runtime_change", recorder)
    return recorder


def _code(result) -> str | None:
    details = getattr(result, "details", None) or {}
    return details.get("domain_code")


def test_reserve_happy_path_returns_payload_and_audits(monkeypatch, audit) -> None:
    project_uuid = uuid.uuid4()
    created_at = "2026-07-29T00:00:00+00:00"

    def fake_reserve(conn, entity_id, reserved_by, note):
        return {
            "id": entity_id,
            "project_uuid": entity_id,
            "kind": "project_reservation",
            "reserved_by": reserved_by,
            "note": note,
            "created_at": created_at,
        }

    monkeypatch.setattr(mod, "reserve_project_uuid", fake_reserve)
    result = _run(action="reserve", project_uuid=str(project_uuid), reserved_by="agent-1", note="why")

    assert isinstance(result, SuccessResult)
    data = result.data
    assert data["project_uuid"] == str(project_uuid)
    assert data["kind"] == "project_reservation"
    assert data["reserved_by"] == "agent-1"
    assert data["note"] == "why"
    assert data["created_at"] == created_at

    assert audit.actions == ["project_uuid_reserve"]
    # plan_uuid is a REQUIRED keyword of record_runtime_change with no default;
    # a reservation is a namespace record, so it must be passed explicitly None.
    assert "plan_uuid" in audit.calls[0]
    assert audit.calls[0]["plan_uuid"] is None
    assert audit.calls[0]["changed_by"] == "agent-1"


def test_reserve_collision_returns_duplicate_id_and_writes_no_audit(monkeypatch, audit) -> None:
    def fake_reserve(conn, entity_id, reserved_by, note):
        raise DuplicateNameError(
            f"entity id already registered: {entity_id} (kind=entity, table=plan)"
        )

    monkeypatch.setattr(mod, "reserve_project_uuid", fake_reserve)
    result = _run(action="reserve", project_uuid=str(uuid.uuid4()), reserved_by="agent-1")

    assert isinstance(result, ErrorResult)
    assert _code(result) == "DUPLICATE_ID"
    assert audit.calls == [], "a refused reserve must write no audit record"


def test_release_happy_path_audits(monkeypatch, audit) -> None:
    released: list[uuid.UUID] = []
    monkeypatch.setattr(
        mod, "release_project_reservation", lambda conn, entity_id: released.append(entity_id)
    )
    project_uuid = uuid.uuid4()
    result = _run(action="release", project_uuid=str(project_uuid), reserved_by="agent-2")

    assert isinstance(result, SuccessResult)
    assert result.data["released"] is True
    assert released == [project_uuid]
    assert audit.actions == ["project_uuid_release"]
    assert audit.calls[0]["plan_uuid"] is None
    assert audit.calls[0]["changed_by"] == "agent-2"


def test_release_absent_reservation_yields_not_found(monkeypatch, audit) -> None:
    def fake_release(conn, entity_id):
        raise NotFoundError(f"project uuid reservation not found: {entity_id}")

    monkeypatch.setattr(mod, "release_project_reservation", fake_release)
    result = _run(action="release", project_uuid=str(uuid.uuid4()), reserved_by="agent-1")

    assert isinstance(result, ErrorResult)
    assert _code(result) == "RESERVATION_NOT_FOUND"
    assert audit.calls == []


def test_resolve_returns_kind_and_never_audits(monkeypatch, audit) -> None:
    project_uuid = uuid.uuid4()
    monkeypatch.setattr(
        mod,
        "resolve_entity_identity",
        lambda conn, entity_id: {
            "id": entity_id,
            "table_name": "",
            "entity_type": "project_reservation",
            "kind": "project_reservation",
            "reserved_by": "agent-1",
            "note": None,
            "created_at": "2026-07-29T00:00:00+00:00",
        },
    )
    result = _run(action="resolve", project_uuid=str(project_uuid), reserved_by="agent-1")
    assert isinstance(result, SuccessResult)
    assert result.data["kind"] == "project_reservation"
    assert audit.calls == [], "resolve is a read and must never audit"


def test_resolve_absent_reservation_yields_not_found(monkeypatch, audit) -> None:
    def fake_resolve(conn, entity_id):
        raise NotFoundError(f"entity identity not found: {entity_id}")

    monkeypatch.setattr(mod, "resolve_entity_identity", fake_resolve)
    result = _run(action="resolve", project_uuid=str(uuid.uuid4()), reserved_by="agent-1")
    assert isinstance(result, ErrorResult)
    assert _code(result) == "RESERVATION_NOT_FOUND"


def test_resolve_of_a_live_entity_is_not_a_reservation(monkeypatch, audit) -> None:
    """An identifier registered as an ordinary entity is not a reservation.

    Reporting it as one would let a caller believe an identifier is merely
    claimed when a live row actually owns it.
    """
    monkeypatch.setattr(
        mod,
        "resolve_entity_identity",
        lambda conn, entity_id: {
            "id": entity_id,
            "table_name": "plan",
            "entity_type": "plan",
            "kind": "entity",
            "reserved_by": None,
            "note": None,
            "created_at": "2026-07-29T00:00:00+00:00",
        },
    )
    result = _run(action="resolve", project_uuid=str(uuid.uuid4()), reserved_by="agent-1")
    assert isinstance(result, ErrorResult)
    assert _code(result) == "RESERVATION_NOT_FOUND"


def test_schema_declares_required_fields() -> None:
    schema = ProjectUuidReserveCommand.get_schema()
    for key in ("action", "project_uuid", "reserved_by", "note"):
        assert key in schema["properties"], f"schema is missing {key}"
    for key in ("action", "project_uuid", "reserved_by"):
        assert key in schema["required"], f"{key} must be required"
    assert schema["properties"]["action"]["enum"] == ["reserve", "release", "resolve"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "params",
    [
        {"action": "delete", "project_uuid": str(uuid.uuid4()), "reserved_by": "a"},
        {"action": "reserve", "project_uuid": "not-a-uuid", "reserved_by": "a"},
        {"action": "reserve", "project_uuid": str(uuid.uuid4()), "reserved_by": "  "},
        {"action": "release", "project_uuid": str(uuid.uuid4()), "reserved_by": "a", "note": "x"},
    ],
    ids=["bad-action", "bad-uuid", "empty-actor", "note-outside-reserve"],
)
def test_validate_params_rejects_malformed_input(params) -> None:
    # Assert on the exception type, which is the contract, not on message prose.
    # The adapter's own schema pass raises ValidationError for enum/required
    # violations before this command's validate_params body runs, so both
    # refusal types are correct outcomes here.
    with pytest.raises((InvalidParamsError, ValidationError)):
        ProjectUuidReserveCommand().validate_params(dict(params))


def test_metadata_documents_error_cases() -> None:
    metadata = ProjectUuidReserveCommand.metadata()
    assert "error_cases" in metadata
    cases = metadata["error_cases"]
    for code in ("DUPLICATE_ID", "RESERVATION_NOT_FOUND", "RUNTIME_VALIDATION_ERROR"):
        assert code in cases, f"metadata does not document {code}"
        # 'solution' is the repository-wide key for remediation text.
        assert cases[code].get("description"), f"{code} has no description"
        assert cases[code].get("solution"), f"{code} has no solution"
