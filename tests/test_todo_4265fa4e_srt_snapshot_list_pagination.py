"""Regression tests for todo 4265fa4e: srt_snapshot_list must not embed
tree_content/vectors by default, must order newest-first with a stable
UUID tie-breaker, and its summary projection must carry every metadata
field the caller's contract requires (uuid, plan_uuid, revision_uuid,
algorithm_version, summarizer_version, embedding_model, tree_hash,
created_at) -- not just the narrower bug-8a13977d field set.

The pagination/view mechanism itself (limit/offset, view=full/summary) was
already shipped by bug 8a13977d (0.1.61); this todo's remaining gaps were:
default view (must be compact, not full), snapshot ordering (must be
newest-first, not oldest-first), and the summary field list (must include
algorithm_version/summarizer_version/embedding_model).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from plan_manager.commands.srt_snapshot_list_command import SrtSnapshotListCommand
from plan_manager.storage import srt_snapshot_store
from plan_manager.storage.srt_snapshot_store import SrtSnapshotRecord


def _record(snapshot_uuid: uuid.UUID, created_at: datetime) -> SrtSnapshotRecord:
    return SrtSnapshotRecord(
        snapshot_uuid=snapshot_uuid,
        plan_uuid=uuid.uuid4(),
        revision_uuid=uuid.uuid4(),
        algorithm_version="1.0.0",
        summarizer_version="1.0.0",
        embedding_model="text-embedding-3-small",
        tree_hash="deadbeef",
        tree_content={"root": {"own_vector": [0.1, 0.2], "children": []}},
        created_at=created_at.isoformat(),
    )


# --------------------------------------------------------------------------
# Storage layer: ordering
# --------------------------------------------------------------------------


def test_list_srt_snapshots_query_orders_newest_first_with_uuid_tiebreaker() -> None:
    source = inspect.getsource(srt_snapshot_store.list_srt_snapshots)
    assert "ORDER BY created_at DESC, uuid DESC" in source
    assert "ORDER BY created_at ASC" not in source


# --------------------------------------------------------------------------
# Entity layer: summary field set
# --------------------------------------------------------------------------


def test_summary_fields_include_the_full_caller_required_metadata_set() -> None:
    assert SrtSnapshotRecord.SUMMARY_FIELDS == (
        "uuid",
        "plan_uuid",
        "revision_uuid",
        "algorithm_version",
        "summarizer_version",
        "embedding_model",
        "tree_hash",
        "created_at",
    )


def test_summary_payload_drops_tree_content_but_keeps_every_other_field() -> None:
    snapshot_uuid = uuid.uuid4()
    record = _record(snapshot_uuid, datetime.now(timezone.utc))
    summary = record.to_summary_payload()

    assert "tree_content" not in summary
    for field in SrtSnapshotRecord.SUMMARY_FIELDS:
        assert field in summary
    assert summary["uuid"] == str(snapshot_uuid)
    assert summary["algorithm_version"] == "1.0.0"
    assert summary["summarizer_version"] == "1.0.0"
    assert summary["embedding_model"] == "text-embedding-3-small"


# --------------------------------------------------------------------------
# Command layer: default view, pagination, ordering-through-the-command
# --------------------------------------------------------------------------


def _patch_list(monkeypatch, records: list[SrtSnapshotRecord]):
    @contextmanager
    def fake_db_connection():
        yield object()

    class _Plan:
        uuid = uuid.uuid4()
        name = "srt-plan"

    monkeypatch.setattr("plan_manager.commands.srt_snapshot_list_command.db_connection", fake_db_connection)
    monkeypatch.setattr("plan_manager.commands.srt_snapshot_list_command.resolve_plan", lambda _conn, _plan: _Plan())
    monkeypatch.setattr("plan_manager.commands.srt_snapshot_list_command.list_srt_snapshots", lambda _conn, _plan_uuid: records)


def test_schema_view_default_is_summary_not_full() -> None:
    schema = SrtSnapshotListCommand.get_schema()
    assert schema["properties"]["view"]["default"] == "summary"
    assert schema["properties"]["view"]["enum"] == ["full", "summary"]


def test_execute_defaults_to_compact_projection_dropping_tree_content(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    records = [_record(uuid.uuid4(), now)]
    _patch_list(monkeypatch, records)

    result = asyncio.run(SrtSnapshotListCommand().execute(plan="srt-plan"))
    data = result.to_dict()["data"]

    assert data["total"] == 1
    snapshot = data["snapshots"][0]
    assert "tree_content" not in snapshot
    assert snapshot["algorithm_version"] == "1.0.0"


def test_execute_view_full_still_available_as_explicit_opt_in(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    records = [_record(uuid.uuid4(), now)]
    _patch_list(monkeypatch, records)

    result = asyncio.run(SrtSnapshotListCommand().execute(plan="srt-plan", view="full"))
    data = result.to_dict()["data"]

    assert "tree_content" in data["snapshots"][0]


def test_execute_paginates_over_whatever_order_the_store_returns(monkeypatch) -> None:
    # The command itself is order-agnostic (it slices whatever
    # list_srt_snapshots returns); ordering correctness is the store's
    # contract, pinned separately above via source inspection.
    now = datetime.now(timezone.utc)
    newest = _record(uuid.uuid4(), now)
    oldest = _record(uuid.uuid4(), now - timedelta(days=1))
    _patch_list(monkeypatch, [newest, oldest])  # store already returns newest-first

    result = asyncio.run(SrtSnapshotListCommand().execute(plan="srt-plan", limit=1, offset=0))
    data = result.to_dict()["data"]

    assert data["total"] == 2
    assert data["snapshots"][0]["uuid"] == str(newest.snapshot_uuid)
