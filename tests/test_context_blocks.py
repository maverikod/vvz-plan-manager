import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.concept import Concept
from plan_manager.domain.paragraph_store import StoredParagraph
from plan_manager.storage.canonical import content_hash
from plan_manager.views import context_blocks
from plan_manager.views.context_blocks import (
    ContextRevision,
    compile_plan_material,
    specific_delta,
    store_context_block,
)


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
REVISION_UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")
COMMON_UUID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _seed(monkeypatch):
    concepts = [
        Concept("C-001", "One", "First concept.", ["alpha"], ["{a111}", "{b222}"]),
        Concept("C-002", "Two", "Second concept.", ["beta"], ["{b222}"]),
        Concept("C-003", "Three", "Third concept.", ["gamma"], ["{c333}"]),
    ]
    paragraphs = [
        StoredParagraph(uuid.uuid4(), PLAN_UUID, "a111", "A text.", 1),
        StoredParagraph(uuid.uuid4(), PLAN_UUID, "b222", "B text.", 2),
        StoredParagraph(uuid.uuid4(), PLAN_UUID, "c333", "C text.", 3),
    ]
    relations = [
        ("C-001", "C-002", "uses"),
        ("C-001", "C-099", "depends_on"),
        ("C-003", "C-001", "extends"),
    ]
    monkeypatch.setattr(context_blocks, "list_concepts", lambda _conn, _plan_uuid: concepts)
    monkeypatch.setattr(context_blocks, "list_paragraphs", lambda _conn, _plan_uuid: paragraphs)
    monkeypatch.setattr(context_blocks, "list_relations", lambda _conn, _plan_uuid: relations)


def test_context_compile_concept_only_is_deterministic(monkeypatch) -> None:
    _seed(monkeypatch)

    first = compile_plan_material(None, PLAN_UUID, ["C-002", "C-001", "C-001"])
    second = compile_plan_material(None, PLAN_UUID, ["C-001", "C-002"])

    assert first == second
    assert content_hash(first) == content_hash(second)
    assert [block["type"] for block in first] == [
        "hrs_fragment",
        "hrs_fragment",
        "mrs_concept",
        "mrs_concept",
        "mrs_relation",
        "mrs_relation",
    ]
    assert {block["label"] for block in first if block["type"] == "hrs_fragment"} == {
        "{a111}",
        "{b222}",
    }
    assert ("C-001", "C-099", "depends_on") in {
        (block["from_concept"], block["to_concept"], block["relation_type"])
        for block in first
        if block["type"] == "mrs_relation"
    }


def test_specific_delta_removes_blocks_already_in_common(monkeypatch) -> None:
    _seed(monkeypatch)
    common_content = compile_plan_material(None, PLAN_UUID, ["C-001", "C-002"])
    common = context_blocks.ContextBlockRecord(
        block_id=COMMON_UUID,
        plan_uuid=PLAN_UUID,
        revision_uuid=REVISION_UUID,
        cascade_uuid=None,
        node_path="G-001",
        child_level=4,
        kind="common",
        common_block_id=None,
        scope_concepts=["C-001", "C-002"],
        content=common_content,
        content_hash=content_hash(common_content),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    scope, delta = specific_delta(None, PLAN_UUID, common, ["C-001"])

    assert scope == ["C-001"]
    assert delta == []


def test_specific_delta_enforces_downward_narrowing(monkeypatch) -> None:
    _seed(monkeypatch)
    common = context_blocks.ContextBlockRecord(
        block_id=COMMON_UUID,
        plan_uuid=PLAN_UUID,
        revision_uuid=REVISION_UUID,
        cascade_uuid=None,
        node_path="G-001",
        child_level=4,
        kind="common",
        common_block_id=None,
        scope_concepts=["C-001"],
        content=[],
        content_hash=content_hash([]),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    with pytest.raises(DomainCommandError) as excinfo:
        specific_delta(None, PLAN_UUID, common, ["C-002"])

    assert excinfo.value.code == "CONCEPT_OUT_OF_SCOPE"
    assert excinfo.value.details["concept_ids"] == ["C-002"]


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _StoreConn:
    def __init__(self):
        self.rows = []
        self.insert_count = 0

    def execute(self, query, params=()):
        # CR-7 G-004: store_context_block's INSERT now arrives through the
        # unified engine as a psycopg sql.Composed statement (identifiers
        # quoted); flatten it the same way the other routed-write fakes do,
        # and the engine's identity-registry admission queries (plain
        # strings, run around the INSERT) need their own canned replies.
        rendered = query.as_string(None) if hasattr(query, "as_string") else query
        flat = " ".join(rendered.replace('"', "").split())
        if flat.startswith("SELECT kind, table_name FROM entity_identity"):
            return _Rows([])
        if flat.startswith("INSERT INTO entity_identity"):
            return _Rows([])
        if flat.startswith("SELECT uuid, plan_uuid"):
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
        if flat.startswith("INSERT INTO context_block"):
            self.insert_count += 1
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
                (
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
                )
            )
            return _Rows([])
        raise AssertionError(flat)


def test_store_context_block_is_idempotent_by_hash() -> None:
    conn = _StoreConn()
    revision = ContextRevision(REVISION_UUID, None)
    content = [{"type": "mrs_concept", "concept_id": "C-001"}]

    first = store_context_block(conn, PLAN_UUID, revision, "plan", 5, "compile", ["C-001"], content)
    second = store_context_block(conn, PLAN_UUID, revision, "plan", 5, "compile", ["C-001"], content)

    assert first.block_id == second.block_id
    assert conn.insert_count == 1


def test_store_context_block_keeps_distinct_empty_specific_scopes() -> None:
    conn = _StoreConn()
    revision = ContextRevision(REVISION_UUID, None)

    first = store_context_block(
        conn,
        PLAN_UUID,
        revision,
        "G-002",
        4,
        "specific",
        ["C-010"],
        [],
        COMMON_UUID,
    )
    second = store_context_block(
        conn,
        PLAN_UUID,
        revision,
        "G-002",
        4,
        "specific",
        ["C-011"],
        [],
        COMMON_UUID,
    )

    assert first.block_id != second.block_id
    assert first.scope_concepts == ["C-010"]
    assert second.scope_concepts == ["C-011"]
    assert conn.insert_count == 2


def test_store_context_block_bug_a795ea4d_keeps_distinct_same_scope_children_by_ref() -> None:
    """Two children of the same parent sharing an IDENTICAL scope (and thus
    identical, here empty, delta content) must still be stored as distinct,
    correctly-attributed rows when given distinct child_ref values -- the
    exact scenario that aliased in bug a795ea4d."""
    conn = _StoreConn()
    revision = ContextRevision(REVISION_UUID, None)

    first = store_context_block(
        conn, PLAN_UUID, revision, "T-001", 5, "specific", ["C-025", "C-026", "C-098"], [], COMMON_UUID, "A-001"
    )
    second = store_context_block(
        conn, PLAN_UUID, revision, "T-001", 5, "specific", ["C-025", "C-026", "C-098"], [], COMMON_UUID, "A-002"
    )

    assert first.block_id != second.block_id
    assert first.child_ref == "A-001"
    assert second.child_ref == "A-002"
    assert first.scope_concepts == second.scope_concepts == ["C-025", "C-026", "C-098"]
    assert conn.insert_count == 2


def test_store_context_block_child_ref_is_idempotent() -> None:
    """A repeated call for the SAME child (same identity, including
    child_ref) reuses the existing row -- content-addressed idempotency is
    preserved, only the missing per-child discrimination was the bug."""
    conn = _StoreConn()
    revision = ContextRevision(REVISION_UUID, None)

    first = store_context_block(
        conn, PLAN_UUID, revision, "T-001", 5, "specific", ["C-025"], [], COMMON_UUID, "A-001"
    )
    second = store_context_block(
        conn, PLAN_UUID, revision, "T-001", 5, "specific", ["C-025"], [], COMMON_UUID, "A-001"
    )

    assert first.block_id == second.block_id
    assert conn.insert_count == 1
