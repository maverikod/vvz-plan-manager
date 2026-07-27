"""Unit coverage for paginated runtime list helper with row projection."""

from __future__ import annotations

from contextlib import contextmanager

from plan_manager.commands import runtime_list_command_helpers as helpers


@contextmanager
def _fake_db():
    yield object()


class _Record:
    SUMMARY_FIELDS = ("uuid", "name")

    def __init__(self, uuid: str, name: str, description: str) -> None:
        self.uuid = uuid
        self.name = name
        self.description = description

    def to_payload(self) -> dict[str, object]:
        return {"uuid": self.uuid, "name": self.name, "description": self.description}

    def to_summary_payload(self) -> dict[str, object]:
        return {"uuid": self.uuid, "name": self.name}


def test_perform_projected_runtime_list_returns_paginated_full_rows(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_projected_runtime_list(
        fetch_records=lambda conn: [
            _Record("1", "a", "A"),
            _Record("2", "b", "B"),
            _Record("3", "c", "C"),
        ],
        result_key="records",
        limit=2,
        offset=1,
        view="full",
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "records": [
            {"uuid": "2", "name": "b", "description": "B"},
            {"uuid": "3", "name": "c", "description": "C"},
        ],
        "total": 3,
        "limit": 2,
        "offset": 1,
    }


def test_perform_projected_runtime_list_honors_summary_default(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_projected_runtime_list(
        fetch_records=lambda conn: [_Record("1", "a", "A")],
        result_key="records",
        limit=None,
        offset=None,
        view=None,
        view_default="summary",
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["records"] == [{"uuid": "1", "name": "a"}]


def test_perform_runtime_list_page_applies_row_mapper(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_list_page(
        fetch_records=lambda conn: [_Record("1", "a", "A"), _Record("2", "b", "B")],
        result_key="records",
        row_mapper=lambda record: {"name": record.name},
        limit=1,
        offset=1,
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "records": [{"name": "b"}],
        "total": 2,
        "limit": 1,
        "offset": 1,
    }
