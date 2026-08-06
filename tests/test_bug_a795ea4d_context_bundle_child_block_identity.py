"""Regression tests for bug a795ea4d: context_bundle aliases empty L5
specific blocks across distinct AS children.

Reported live on 0.1.63: context_bundle(node=G-005/T-001, child_level=5,
children=[A-001..A-005], each scoped to the SAME live concepts
C-025/C-026/C-098) returned ONE shared specific block_id for all five
children. Root cause: store_context_block's idempotent-dedup identity
(mirroring the context_block_idempotent unique index) keys a 'specific'
block on (plan, revision/cascade, node_path, child_level, kind,
common_block, scope_concepts, content_hash) with NO per-child
discriminator. When several children of the same parent legitimately share
an identical concept scope, their compiled delta is byte-identical (worst
case: empty, when the scope is already fully covered by the parent's
common block) and hashes the same, so every child after the first silently
reused the first child's stored row -- losing per-child attribution
entirely for the empty-delta case (block_get showed total=0, blocks=[],
content=[], no way to tell which child it belonged to).

Fix: thread each child's supplied 'ref' through specific-block storage as
an explicit child_ref identity column, so every supplied child reference
gets its own addressable, correctly-attributed row even when scope and
content are identical to a sibling's.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import context_bundle_command
from plan_manager.commands.context_bundle_command import ContextBundleCommand
from plan_manager.domain.concept import Concept
from plan_manager.views import context_blocks


class _Plan:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = "a795ea4d-plan"
        self.head_revision_uuid = uuid.uuid4()


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _StoreConn:
    """Minimal fake connection backing context_block SELECT/INSERT.

    Mirrors store_context_block's/get_context_block's real SQL param
    layout exactly (row = (block_id, plan_uuid, revision_uuid,
    cascade_uuid, node_path, child_level, kind, common_block_id,
    scope_concepts, content, content_hash, created_at, child_ref)), so
    this test exercises the real dedup identity against real
    store_context_block/specific_delta code -- not a mocked shortcut
    around it. This emulates the DB unique index context_block_idempotent
    (migration 0023: plan/revision/cascade/node_path/child_level/kind/
    common_block/scope_concepts/content_hash/child_ref).
    """

    def __init__(self):
        self.rows = []

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
                # get_context_block: direct primary-key style lookup.
                plan_uuid, block_id = params
                matches = [row for row in self.rows if row[1] == plan_uuid and row[0] == block_id]
                return _Rows(matches)
            # store_context_block's idempotent-dedup lookup. params order:
            # (plan_uuid, revision_uuid, cascade_uuid, node_path,
            #  child_level, kind, content_hash, common_block_id,
            #  scope_concepts, child_ref).
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

    concepts = [
        Concept("C-025", "Alpha", "Concept alpha.", [], []),
        Concept("C-026", "Beta", "Concept beta.", [], []),
        Concept("C-098", "Gamma", "Concept gamma.", [], []),
    ]
    monkeypatch.setattr(context_blocks, "list_concepts", lambda _conn, _plan_uuid: concepts)
    monkeypatch.setattr(context_blocks, "list_paragraphs", lambda _conn, _plan_uuid: [])
    monkeypatch.setattr(context_blocks, "list_relations", lambda _conn, _plan_uuid: [])
    monkeypatch.setattr(context_blocks, "load_steps", lambda _conn, _plan_uuid: {})
    monkeypatch.setattr(context_bundle_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(context_bundle_command, "resolve_plan", lambda _conn, _plan: plan)
    return plan, conn


def _children(n: int) -> list[dict[str, object]]:
    return [
        {"ref": f"A-{i:03d}", "concepts": ["C-025", "C-026", "C-098"]}
        for i in range(1, n + 1)
    ]


def test_distinct_as_children_with_identical_scope_get_distinct_specific_blocks(monkeypatch):
    """G-005/T-001 with 5 AS children (A-001..A-005), each scoped to the SAME
    concepts (C-025/C-026/C-098, fully covered by the T-001 common block)
    must still receive 5 DISTINCT, correctly-attributed specific block_ids
    -- even though every child's compiled delta is legitimately empty."""
    _patch(monkeypatch)

    result = asyncio.run(
        ContextBundleCommand().execute(
            plan="a795ea4d-plan",
            node="plan",
            child_level=5,
            children=_children(5),
            shared_concepts=["C-025", "C-026", "C-098"],
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True, payload
    children = payload["data"]["children"]

    assert len(children) == 5
    # Every child's compiled delta is legitimately empty (fully covered by common).
    for child in children:
        assert child["total"] == 0
        assert child["blocks"] == []
        assert child["content"] == []

    refs = [child["ref"] for child in children]
    block_ids = [child["block_id"] for child in children]
    assert refs == ["A-001", "A-002", "A-003", "A-004", "A-005"]
    assert len(set(block_ids)) == 5, (
        f"bug a795ea4d: expected 5 distinct specific block_ids for 5 distinct "
        f"AS children, got aliasing -- {block_ids}"
    )


def test_each_specific_block_is_readable_back_with_correct_child_attribution(monkeypatch):
    """block_get path: each child's own stored context_block row, read back
    directly (as BlockGetCommand does via get_context_block), must be keyed
    to -- and identify -- its own child, not a sibling's."""
    plan, conn = _patch(monkeypatch)

    result = asyncio.run(
        ContextBundleCommand().execute(
            plan="a795ea4d-plan",
            node="plan",
            child_level=5,
            children=_children(5),
            shared_concepts=["C-025", "C-026", "C-098"],
        )
    )
    children = result.to_dict()["data"]["children"]

    seen_block_ids = set()
    for child in children:
        block_id = uuid.UUID(child["block_id"])
        assert block_id not in seen_block_ids, (
            f"bug a795ea4d: block_id {block_id} already served to a different "
            f"child -- aliasing reproduced"
        )
        seen_block_ids.add(block_id)
        record = context_blocks.get_context_block(conn, plan.uuid, block_id)
        assert record.child_ref == child["ref"], (
            f"specific block {block_id} attributed to child_ref="
            f"{record.child_ref!r}, expected {child['ref']!r}"
        )
