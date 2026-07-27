"""Regression tests for TODO 60c3a375: batch context-block rebuild with
summary rows instead of full block bodies.

The original operator pain-point was mechanical context drift after a
revision change: dozens of stale context blocks had to be rebuilt one by
one, and the only available compile commands (`context_common`,
`context_specific`, `context_bundle`) return the full `blocks`/`content`
payload for every rebuilt block. For large common scopes that payload is
thousands of tokens per call, making bulk repair of invalidated context
blocks impractical.

Acceptance contract for the new command:

1. It accepts multiple stored block_ids and rebuilds their equivalent
   blocks against the CURRENT working state.
2. It returns only compact per-block summaries, never the heavy
   `blocks`/`content` bodies inline.
3. A stale `specific` block is rebuilt against a freshly rebuilt current
   `common` block for the same parent scope, not against its stale source
   common row.
4. Top-level pagination follows the uniform limit/offset envelope.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import block_rebuild_command
from plan_manager.commands.block_rebuild_command import BlockRebuildCommand
from plan_manager.views import context_blocks
from plan_manager.views.context_blocks import (
    ContextRevision,
    compile_context,
    common_context,
    get_context_block,
    specific_delta,
    store_context_block,
)


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-00000000f601")
OLD_REV = uuid.UUID("00000000-0000-0000-0000-00000000f602")
NEW_REV = uuid.UUID("00000000-0000-0000-0000-00000000f603")


class _Plan:
    def __init__(self) -> None:
        self.uuid = PLAN_UUID
        self.name = "todo-60c3a375"
        self.head_revision_uuid = NEW_REV


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
            (
                block_id,
                plan_uuid,
                revision_uuid,
                cascade_uuid,
                node_path,
                child_level,
                kind,
                common_block_id,
                scope_concepts,
                content,
                hash_value,
                created_at,
                child_ref,
            ) = params
            self.rows.append(
                [
                    block_id,
                    plan_uuid,
                    revision_uuid,
                    cascade_uuid,
                    node_path,
                    child_level,
                    kind,
                    common_block_id,
                    list(scope_concepts),
                    content.obj,
                    hash_value,
                    created_at,
                    child_ref,
                ]
            )
            return _Rows([])
        raise AssertionError(f"unexpected query: {query}")


def _patch(monkeypatch):
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
        lambda _conn, _plan_uuid: [
            _Concept("C-001", ["{a111}"]),
            _Concept("C-002", ["{b222}"]),
        ],
    )
    monkeypatch.setattr(
        context_blocks,
        "list_paragraphs",
        lambda _conn, _plan_uuid: [
            _Paragraph("a111", "Alpha paragraph.", 1),
            _Paragraph("b222", "Beta paragraph.", 2),
        ],
    )
    monkeypatch.setattr(
        context_blocks,
        "list_relations",
        lambda _conn, _plan_uuid: [("C-001", "C-002", "uses")],
    )
    monkeypatch.setattr(context_blocks, "load_steps", lambda _conn, _plan_uuid: {})
    monkeypatch.setattr(context_blocks, "get_open_cascade", lambda _conn, _plan_uuid: None)
    monkeypatch.setattr(block_rebuild_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(block_rebuild_command, "resolve_plan", lambda _conn, _plan: plan)
    return plan, conn


def test_block_rebuild_rebuilds_specific_against_current_common_and_returns_only_summaries(monkeypatch):
    plan, conn = _patch(monkeypatch)
    old_revision = ContextRevision(OLD_REV, None)
    node_path, scope, common_content = common_context(conn, plan.uuid, "plan", 5, ["C-001", "C-002"])
    stale_common = store_context_block(conn, plan.uuid, old_revision, node_path, 5, "common", scope, common_content)
    specific_scope, specific_content = specific_delta(conn, plan.uuid, stale_common, ["C-001"])
    stale_specific = store_context_block(
        conn,
        plan.uuid,
        old_revision,
        node_path,
        5,
        "specific",
        specific_scope,
        specific_content,
        stale_common.block_id,
        "A-001",
    )

    result = asyncio.run(
        BlockRebuildCommand().execute(
            plan=plan.name,
            block_ids=[str(stale_common.block_id), str(stale_specific.block_id)],
            limit=1,
            offset=1,
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True, payload
    data = payload["data"]

    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 1
    assert len(data["blocks"]) == 1

    summary = data["blocks"][0]
    assert set(summary) == {
        "source_block_id",
        "block_id",
        "hash",
        "kind",
        "node_path",
        "child_level",
        "revision_uuid",
        "cascade_uuid",
        "common_block_id",
        "child_ref",
        "is_current",
    }
    assert summary["source_block_id"] == str(stale_specific.block_id)
    assert summary["block_id"] != str(stale_specific.block_id)
    assert summary["kind"] == "specific"
    assert summary["node_path"] == "plan"
    assert summary["child_level"] == 5
    assert summary["revision_uuid"] == str(NEW_REV)
    assert summary["cascade_uuid"] is None
    assert summary["child_ref"] == "A-001"
    assert summary["is_current"] is True

    rebuilt_common = get_context_block(conn, plan.uuid, uuid.UUID(summary["common_block_id"]))
    rebuilt_specific = get_context_block(conn, plan.uuid, uuid.UUID(summary["block_id"]))
    assert rebuilt_common.block_id != stale_common.block_id
    assert rebuilt_common.revision_uuid == NEW_REV
    assert rebuilt_specific.revision_uuid == NEW_REV
    assert rebuilt_specific.common_block_id == rebuilt_common.block_id


def test_block_rebuild_rebuilds_compile_rows_and_infers_include_flags_from_stored_shape(monkeypatch):
    plan, conn = _patch(monkeypatch)
    old_revision = ContextRevision(OLD_REV, None)
    content, scope = compile_context(
        conn,
        plan.uuid,
        ["C-001"],
        5,
        {"authoring_template": False, "standards": True, "field_schema": False},
        "plan",
    )
    stale_compile = store_context_block(conn, plan.uuid, old_revision, "plan", 5, "compile", scope, content)

    result = asyncio.run(BlockRebuildCommand().execute(plan=plan.name, block_ids=[str(stale_compile.block_id)]))
    payload = result.to_dict()
    assert payload["success"] is True, payload

    summary = payload["data"]["blocks"][0]
    assert "blocks" not in summary
    assert "content" not in summary
    rebuilt = get_context_block(conn, plan.uuid, uuid.UUID(summary["block_id"]))
    assert [block["type"] for block in rebuilt.content] == [block["type"] for block in stale_compile.content]
    assert rebuilt.revision_uuid == NEW_REV
