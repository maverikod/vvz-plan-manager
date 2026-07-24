"""Regression tests for bug 03956ccf: context_bundle returned an
unpaginated full context payload (the compiled 'common' block, and each
child's own delta block, can grow to hundreds of entries when the parent
scope is plan-wide) that exceeded agent response limits. Related open todo
(same intent, -10): "Bound and paginate context_bundle common-block output".

context_bundle now applies the SAME uniform limit/offset pagination
contract already used by block_get (todo eb2dcccb: bounded default 50, max
200) to the 'common' block's entry list and to every 'children[i]' entry's
own entry list; a bundle whose blocks are all within the default page size
(the common case) is byte-compatible beyond the additive
'total'/'limit'/'offset' keys.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import context_bundle_command
from plan_manager.commands.context_bundle_command import ContextBundleCommand
from plan_manager.commands.runtime_filtering import pagination_schema_properties
from plan_manager.views.context_blocks import ContextBlockRecord, ContextRevision


class _Plan:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = "bundle-plan"
        self.head_revision_uuid = uuid.uuid4()


def _content(n: int, prefix: str = "frag") -> list[dict[str, object]]:
    return [{"type": "hrs_fragment", "label": f"{prefix}-{i:03d}", "text": "x"} for i in range(n)]


def _record(node_path: str, level: int, kind: str, content: list[dict[str, object]], common_block_id=None) -> ContextBlockRecord:
    return ContextBlockRecord(
        block_id=uuid.uuid4(),
        plan_uuid=uuid.uuid4(),
        revision_uuid=uuid.uuid4(),
        cascade_uuid=None,
        node_path=node_path,
        child_level=level,
        kind=kind,
        common_block_id=common_block_id,
        scope_concepts=["C-001"],
        content=content,
        content_hash="deadbeef",
        created_at="2026-07-23T00:00:00+00:00",
    )


def _children(n: int) -> list[dict[str, object]]:
    return [{"ref": f"child-{i}", "concepts": ["C-001"]} for i in range(n)]


def _patch(monkeypatch, *, common_entry_count: int, child_entry_count: int) -> _Plan:
    plan = _Plan()
    revision = ContextRevision(plan.head_revision_uuid, None)

    @contextmanager
    def fake_db_connection():
        yield object()

    def fake_common_context(conn, plan_uuid, node, child_level, shared_concepts):
        return "plan", ["C-001"], _content(common_entry_count)

    def fake_store_context_block(conn, plan_uuid, ctx_revision, node_path, level, kind, scope, content, common_block_id=None):
        return _record(node_path, level, kind, content, common_block_id)

    def fake_specific_delta(conn, plan_uuid, common, concepts):
        return concepts, _content(child_entry_count, prefix="delta")

    monkeypatch.setattr(context_bundle_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(context_bundle_command, "resolve_plan", lambda _conn, _plan: plan)
    monkeypatch.setattr(context_bundle_command, "resolve_context_revision", lambda _conn, _p, _rev, _casc: revision)
    monkeypatch.setattr(context_bundle_command, "common_context", fake_common_context)
    monkeypatch.setattr(context_bundle_command, "store_context_block", fake_store_context_block)
    monkeypatch.setattr(context_bundle_command, "specific_delta", fake_specific_delta)
    return plan


def test_schema_declares_uniform_pagination_properties():
    properties = ContextBundleCommand.get_schema()["properties"]
    canonical = pagination_schema_properties()
    assert properties["limit"] == canonical["limit"]
    assert properties["offset"] == canonical["offset"]


def test_small_bundle_is_byte_compatible_beyond_the_new_pagination_keys(monkeypatch):
    """A common/child block within the default page size (50) returns every entry, unchanged."""
    _patch(monkeypatch, common_entry_count=5, child_entry_count=3)

    result = asyncio.run(
        ContextBundleCommand().execute(plan="bundle-plan", node="plan", child_level=4, children=_children(1))
    )
    data = result.to_dict()["data"]
    common = data["common"]
    child = data["children"][0]

    assert len(common["blocks"]) == 5
    assert len(common["content"]) == 5
    assert common["total"] == 5
    assert common["limit"] == 50
    assert common["offset"] == 0
    assert len(child["blocks"]) == 3
    assert child["total"] == 3
    assert child["limit"] == 50
    assert child["offset"] == 0


def test_large_common_block_is_bounded_by_default_page_size(monkeypatch):
    """The observed defect: a plan-wide common context block must never dump
    its whole entry list in one response."""
    _patch(monkeypatch, common_entry_count=300, child_entry_count=5)

    result = asyncio.run(
        ContextBundleCommand().execute(plan="bundle-plan", node="plan", child_level=4, children=_children(1))
    )
    common = result.to_dict()["data"]["common"]

    assert len(common["blocks"]) == 50  # DEFAULT_LIMIT, not the full 300
    assert common["total"] == 300
    assert common["limit"] == 50
    assert common["offset"] == 0
    assert common["block_id"]  # caller can page on with block_get
    assert common["common_block_id"] == common["block_id"]


def test_large_child_delta_is_also_bounded(monkeypatch):
    _patch(monkeypatch, common_entry_count=5, child_entry_count=120)

    result = asyncio.run(
        ContextBundleCommand().execute(plan="bundle-plan", node="plan", child_level=4, children=_children(1))
    )
    child = result.to_dict()["data"]["children"][0]

    assert len(child["blocks"]) == 50
    assert child["total"] == 120
    assert child["limit"] == 50
    assert child["offset"] == 0


def test_explicit_limit_and_offset_slice_the_stored_order(monkeypatch):
    _patch(monkeypatch, common_entry_count=10, child_entry_count=5)

    result = asyncio.run(
        ContextBundleCommand().execute(
            plan="bundle-plan", node="plan", child_level=4, children=_children(1), limit=3, offset=4
        )
    )
    common = result.to_dict()["data"]["common"]

    assert [b["label"] for b in common["blocks"]] == ["frag-004", "frag-005", "frag-006"]
    assert common["total"] == 10
    assert common["limit"] == 3
    assert common["offset"] == 4


def test_pagination_covers_every_common_entry_with_no_duplicates_or_gaps(monkeypatch):
    _patch(monkeypatch, common_entry_count=120, child_entry_count=1)

    seen: list[str] = []
    offset = 0
    while True:
        result = asyncio.run(
            ContextBundleCommand().execute(
                plan="bundle-plan", node="plan", child_level=4, children=_children(1), limit=50, offset=offset
            )
        )
        common = result.to_dict()["data"]["common"]
        seen.extend(entry["label"] for entry in common["blocks"])
        if offset + common["limit"] >= common["total"]:
            break
        offset += common["limit"]

    assert seen == [f"frag-{i:03d}" for i in range(120)]
    assert len(seen) == len(set(seen)) == 120


def test_invalid_pagination_surfaces_invalid_pagination_domain_code(monkeypatch):
    _patch(monkeypatch, common_entry_count=5, child_entry_count=5)

    result = asyncio.run(
        ContextBundleCommand().execute(plan="bundle-plan", node="plan", child_level=4, children=_children(1), limit=0)
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_multiple_children_each_carry_independent_pagination_metadata(monkeypatch):
    _patch(monkeypatch, common_entry_count=5, child_entry_count=60)

    result = asyncio.run(
        ContextBundleCommand().execute(plan="bundle-plan", node="plan", child_level=4, children=_children(2))
    )
    children = result.to_dict()["data"]["children"]

    assert len(children) == 2
    for child in children:
        assert len(child["blocks"]) == 50
        assert child["total"] == 60
