"""Regression tests for todo eb2dcccb: block_get for a large common context
block produced ~76,969 tokens and truncated the MCP response (observed on
common context block 292bc78c-8513-4a9d-8f10-ac5ca088fab9). block_get's
'blocks'/'content' entry list is now paginated with the shared uniform
limit/offset contract (bounded default 50, max 200), while small blocks
(entry count within the default page) return exactly as before.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import block_get_command
from plan_manager.commands.block_get_command import BlockGetCommand
from plan_manager.views.context_blocks import ContextBlockRecord


def _record(entry_count: int) -> ContextBlockRecord:
    content = [{"type": "hrs_fragment", "label": f"frag-{i:03d}", "text": "x"} for i in range(entry_count)]
    return ContextBlockRecord(
        block_id=uuid.uuid4(),
        plan_uuid=uuid.uuid4(),
        revision_uuid=uuid.uuid4(),
        cascade_uuid=None,
        node_path="plan",
        child_level=3,
        kind="common",
        common_block_id=None,
        scope_concepts=["C-001"],
        content=content,
        content_hash="deadbeef",
        created_at="2026-07-23T00:00:00+00:00",
    )


class _Plan:
    def __init__(self):
        self.uuid = uuid.uuid4()
        self.name = "block-plan"


def _patch(monkeypatch, record: ContextBlockRecord):
    @contextmanager
    def fake_db_connection():
        yield object()

    monkeypatch.setattr(block_get_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(block_get_command, "resolve_plan", lambda _conn, _plan: _Plan())
    monkeypatch.setattr(block_get_command, "get_context_block", lambda _conn, _plan_uuid, _block_id: record)
    monkeypatch.setattr(
        block_get_command, "current_working_state", lambda _conn, _plan: (record.revision_uuid, record.cascade_uuid)
    )


def test_schema_declares_uniform_pagination_properties():
    from plan_manager.commands.runtime_filtering import pagination_schema_properties

    properties = BlockGetCommand.get_schema()["properties"]
    canonical = pagination_schema_properties()
    assert properties["limit"] == canonical["limit"]
    assert properties["offset"] == canonical["offset"]


def test_small_block_is_byte_compatible_beyond_the_new_pagination_keys(monkeypatch):
    """A block within the default page size (50) returns every entry, unchanged."""
    record = _record(5)
    _patch(monkeypatch, record)

    result = asyncio.run(BlockGetCommand().execute(plan="block-plan", block_id=str(record.block_id)))
    data = result.to_dict()["data"]

    assert len(data["blocks"]) == 5
    assert len(data["content"]) == 5
    assert data["blocks"] == record.content
    assert data["total"] == 5
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["is_current"] is True


def test_large_block_is_bounded_by_default_page_size(monkeypatch):
    """The observed defect: an oversized block must never dump its whole entry list."""
    record = _record(250)
    _patch(monkeypatch, record)

    result = asyncio.run(BlockGetCommand().execute(plan="block-plan", block_id=str(record.block_id)))
    data = result.to_dict()["data"]

    assert len(data["blocks"]) == 50  # DEFAULT_LIMIT, not the full 250
    assert data["total"] == 250
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_pagination_covers_every_entry_with_no_duplicates_or_gaps(monkeypatch):
    record = _record(120)
    _patch(monkeypatch, record)

    seen: list[str] = []
    offset = 0
    while True:
        result = asyncio.run(
            BlockGetCommand().execute(plan="block-plan", block_id=str(record.block_id), limit=50, offset=offset)
        )
        data = result.to_dict()["data"]
        seen.extend(entry["label"] for entry in data["blocks"])
        if offset + data["limit"] >= data["total"]:
            break
        offset += data["limit"]

    assert seen == [f"frag-{i:03d}" for i in range(120)]
    assert len(seen) == len(set(seen)) == 120


def test_explicit_limit_and_offset_slice_the_stored_order(monkeypatch):
    record = _record(10)
    _patch(monkeypatch, record)

    result = asyncio.run(
        BlockGetCommand().execute(plan="block-plan", block_id=str(record.block_id), limit=3, offset=4)
    )
    data = result.to_dict()["data"]

    assert [e["label"] for e in data["blocks"]] == ["frag-004", "frag-005", "frag-006"]
    assert data["total"] == 10
    assert data["limit"] == 3
    assert data["offset"] == 4


def test_invalid_pagination_surfaces_invalid_pagination_domain_code(monkeypatch):
    record = _record(5)
    _patch(monkeypatch, record)

    result = asyncio.run(
        BlockGetCommand().execute(plan="block-plan", block_id=str(record.block_id), limit=0)
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_malformed_uuid_still_rejected_before_pagination_is_considered(monkeypatch):
    @contextmanager
    def fake_db():
        yield object()

    monkeypatch.setattr(block_get_command, "db_connection", fake_db)
    monkeypatch.setattr(block_get_command, "resolve_plan", lambda _conn, _plan: _Plan())

    result = asyncio.run(BlockGetCommand().execute(plan="block-plan", block_id="not-a-uuid"))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"
