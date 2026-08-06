"""Regression tests for bug e3060750: block_rebuild must honor an open cascade.

block_rebuild resolved its target identity with a bare
resolve_context_revision(conn, plan) call, which returns the COMMITTED head
even while a cascade is open. Rebuilt blocks therefore carried
(head_revision, cascade_uuid=None) identity, reported is_current=true
against that same pair, and were immediately rejected as stale by the
gate's context_coverage.common_current check, which compares against the
LIVE working state (cascade tip + cascade uuid). The fix defaults the
command to current_working_state and accepts an optional explicit
cascade_uuid pin.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import block_rebuild_command
from plan_manager.commands.block_rebuild_command import BlockRebuildCommand
from plan_manager.views import context_blocks
from plan_manager.views.context_blocks import (
    ContextRevision,
    common_context,
    get_context_block,
    store_context_block,
)


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-00000000e301")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-00000000e302")
CASCADE_TIP = uuid.UUID("00000000-0000-0000-0000-00000000e303")
CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-00000000e304")


class _Plan:
    def __init__(self) -> None:
        self.uuid = PLAN_UUID
        self.name = "bug-e3060750"
        self.head_revision_uuid = HEAD_REV


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _StoreConn:
    def __init__(self) -> None:
        self.rows: list[list[object]] = []

    def execute(self, query, params=()):
        # CR-7 G-004: store_context_block's INSERT now arrives through the
        # unified engine as a psycopg sql.Composed statement (identifiers
        # quoted); flatten it the same way the other routed-write fakes do,
        # and the engine's identity-registry admission queries (plain
        # strings, run around the INSERT) need their own canned replies.
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        query = " ".join(rendered.replace('"', "").split())
        if query.startswith("SELECT kind, table_name FROM entity_identity"):
            return _Rows([])
        if query.startswith("INSERT INTO entity_identity"):
            return _Rows([])
        if query.startswith("SELECT uuid, plan_uuid"):
            if "WHERE plan_uuid = %s AND uuid = %s" in query:
                plan_uuid, block_id = params
                matches = [row for row in self.rows if row[1] == plan_uuid and row[0] == block_id]
                return _Rows(matches)
            matches = [
                row
                for row in self.rows
                if row[1] == params[0]
                and row[2] == params[1]
                and row[3] == params[2]
                and row[4] == params[3]
                and row[5] == params[4]
                and row[6] == params[5]
                and row[10] == params[6]
                and row[7] == params[7]
                and row[8] == list(params[8])
                and row[12] == params[9]
            ]
            return _Rows(matches)
        if query.startswith("INSERT INTO context_block"):
            self.rows.append(
                [
                    params[0],
                    params[1],
                    params[2],
                    params[3],
                    params[4],
                    params[5],
                    params[6],
                    params[7],
                    list(params[8]),
                    params[9].obj,
                    params[10],
                    params[11],
                    params[12],
                ]
            )
            return _Rows([])
        raise AssertionError(f"unexpected query: {query}")


def _open_cascade() -> CascadeRecord:
    return CascadeRecord(
        uuid=CASCADE_UUID,
        plan_uuid=PLAN_UUID,
        name="cascade/e3060750",
        base_revision_uuid=HEAD_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


def _patch(monkeypatch, cascade: CascadeRecord | None):
    plan = _Plan()
    conn = _StoreConn()

    @contextmanager
    def fake_db_connection():
        yield conn

    class _Concept:
        def __init__(self, concept_id: str, source_labels: list[str]) -> None:
            self.concept_id = concept_id
            self.name = concept_id
            self.definition = concept_id
            self.properties = []
            self.source_labels = source_labels

    class _Paragraph:
        def __init__(self, label: str, text: str, position: int) -> None:
            self.label = label
            self.text = text
            self.position = position

    monkeypatch.setattr(
        context_blocks,
        "list_concepts",
        lambda _conn, _plan_uuid: [_Concept("C-001", ["{a111}"])],
    )
    monkeypatch.setattr(
        context_blocks,
        "list_paragraphs",
        lambda _conn, _plan_uuid: [_Paragraph("a111", "Alpha paragraph.", 1)],
    )
    monkeypatch.setattr(context_blocks, "list_relations", lambda _conn, _plan_uuid: [])
    monkeypatch.setattr(context_blocks, "load_steps", lambda _conn, _plan_uuid: {})
    monkeypatch.setattr(context_blocks, "get_open_cascade", lambda _conn, _plan_uuid: cascade)
    monkeypatch.setattr(context_blocks, "get_ref", lambda _conn, _plan_uuid, _name: CASCADE_TIP)
    monkeypatch.setattr(block_rebuild_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(block_rebuild_command, "resolve_plan", lambda _conn, _plan: plan)
    return plan, conn


def _stale_common(conn, plan) -> uuid.UUID:
    node_path, scope, content = common_context(conn, plan.uuid, "plan", 5, ["C-001"])
    stale = store_context_block(
        conn, plan.uuid, ContextRevision(uuid.uuid4(), None), node_path, 5, "common", scope, content
    )
    return stale.block_id


def test_rebuild_defaults_to_open_cascade_working_state(monkeypatch):
    plan, conn = _patch(monkeypatch, _open_cascade())
    stale_id = _stale_common(conn, plan)

    result = asyncio.run(BlockRebuildCommand().execute(plan=plan.name, block_ids=[str(stale_id)]))
    payload = result.to_dict()
    assert payload["success"] is True, payload
    summary = payload["data"]["blocks"][0]

    assert summary["revision_uuid"] == str(CASCADE_TIP)
    assert summary["cascade_uuid"] == str(CASCADE_UUID)
    assert summary["is_current"] is True

    rebuilt = get_context_block(conn, plan.uuid, uuid.UUID(summary["block_id"]))
    assert rebuilt.revision_uuid == CASCADE_TIP
    assert rebuilt.cascade_uuid == CASCADE_UUID


def test_rebuild_accepts_explicit_cascade_pin(monkeypatch):
    plan, conn = _patch(monkeypatch, _open_cascade())
    stale_id = _stale_common(conn, plan)

    result = asyncio.run(
        BlockRebuildCommand().execute(
            plan=plan.name, block_ids=[str(stale_id)], cascade_uuid=str(CASCADE_UUID)
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True, payload
    summary = payload["data"]["blocks"][0]
    assert summary["revision_uuid"] == str(CASCADE_TIP)
    assert summary["cascade_uuid"] == str(CASCADE_UUID)
    assert summary["is_current"] is True


def test_rebuild_without_cascade_still_targets_head(monkeypatch):
    plan, conn = _patch(monkeypatch, None)
    stale_id = _stale_common(conn, plan)

    result = asyncio.run(BlockRebuildCommand().execute(plan=plan.name, block_ids=[str(stale_id)]))
    payload = result.to_dict()
    assert payload["success"] is True, payload
    summary = payload["data"]["blocks"][0]
    assert summary["revision_uuid"] == str(HEAD_REV)
    assert summary["cascade_uuid"] is None
    assert summary["is_current"] is True
