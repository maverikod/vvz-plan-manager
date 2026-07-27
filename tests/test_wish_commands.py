"""Command-level coverage for the runtime wish CRUD surface."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import uuid

from plan_manager.commands import runtime_delete_command_helpers
from plan_manager.commands import runtime_record_command_helpers
from plan_manager.commands import wish_create_command, wish_delete_command, wish_get_command, wish_list_command, wish_update_command
from plan_manager.commands.wish_create_command import WishCreateCommand
from plan_manager.commands.wish_delete_command import WishDeleteCommand
from plan_manager.commands.wish_get_command import WishGetCommand
from plan_manager.commands.wish_list_command import WishListCommand
from plan_manager.commands.wish_update_command import WishUpdateCommand
from plan_manager.domain.wish import WishItem


@contextmanager
def _fake_db():
    yield object()


def _wish(**overrides) -> WishItem:
    fields = {
        "wish_uuid": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "title": "Calendar graph",
        "description": "Need a calendar graph for work planning.",
        "kind": "feature",
        "status": "proposed",
        "priority_nice": -4,
        "created_by": "owner",
        "assigned_to": "agent",
        "target_release": "0.1.70",
        "rationale": "High-value planning surface.",
        "created_at": "2026-07-26T00:00:00+00:00",
        "updated_at": "2026-07-26T00:00:00+00:00",
        "decided_at": None,
        "delivered_at": None,
        "primary_anchor_type": "none",
        "anchor_project_id": None,
        "anchor_file_path": None,
        "anchor_plan_uuid": None,
        "anchor_revision_uuid": None,
        "anchor_step_uuid": None,
        "anchor_step_path": None,
        "anchor_ref_id": None,
        "deleted_at": None,
    }
    fields.update(overrides)
    return WishItem(**fields)


def test_wish_create_returns_created_payload(monkeypatch) -> None:
    created = _wish()
    monkeypatch.setattr(wish_create_command, "db_connection", _fake_db)
    monkeypatch.setattr(wish_create_command, "create_wish", lambda conn, **kwargs: created)

    result = asyncio.run(
        WishCreateCommand().execute(
            title="Calendar graph",
            description="Need a calendar graph for work planning.",
            kind="feature",
            priority_nice=-4,
            created_by="owner",
            anchor_type="none",
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["wish_uuid"] == str(created.wish_uuid)


def test_wish_list_returns_uniform_page_envelope(monkeypatch) -> None:
    monkeypatch.setattr(wish_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(wish_list_command, "list_wishes_page", lambda conn, **kwargs: ([_wish()], 1))

    result = asyncio.run(WishListCommand().execute(limit=5, offset=0)).to_dict()

    assert result["success"] is True
    data = result["data"]
    assert set(data) == {"wishes", "total", "limit", "offset"}
    assert data["total"] == 1
    assert data["limit"] == 5
    assert data["offset"] == 0


def test_wish_get_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(runtime_record_command_helpers, "db_connection", _fake_db)
    monkeypatch.setattr(wish_get_command, "get_wish", lambda conn, wish_uuid: _wish())

    result = asyncio.run(
        WishGetCommand().execute("11111111-1111-1111-1111-111111111111")
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["wish_uuid"] == "11111111-1111-1111-1111-111111111111"


def test_wish_update_returns_updated_payload(monkeypatch) -> None:
    monkeypatch.setattr(runtime_record_command_helpers, "db_connection", _fake_db)
    monkeypatch.setattr(wish_update_command, "get_wish", lambda conn, wish_uuid: _wish())
    monkeypatch.setattr(
        wish_update_command,
        "update_wish",
        lambda conn, wish_uuid, **kwargs: _wish(status=kwargs["status"]),
    )

    result = asyncio.run(
        WishUpdateCommand().execute(
            wish="11111111-1111-1111-1111-111111111111",
            changed_by="owner",
            status="planned",
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["status"] == "planned"


def test_wish_delete_dry_run_reports_reference_blockers(monkeypatch) -> None:
    monkeypatch.setattr(runtime_delete_command_helpers, "db_connection", _fake_db)
    monkeypatch.setattr(wish_delete_command, "get_wish", lambda conn, wish_uuid: _wish())
    monkeypatch.setattr(
        wish_delete_command.WishItem,
        "crud_reference_counts",
        classmethod(lambda cls, conn, entity_id: {"calendar_entry.wish_uuid": 2}),
    )

    result = asyncio.run(
        WishDeleteCommand().execute(
            wish="11111111-1111-1111-1111-111111111111",
            changed_by="owner",
            dry_run=True,
        )
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["blocked"] is True
    assert result["data"]["references"] == {"calendar_entry.wish_uuid": 2}
