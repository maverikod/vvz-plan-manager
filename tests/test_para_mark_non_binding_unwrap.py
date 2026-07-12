"""Regression test for bug f253b08d: para_mark_non_binding unwrap was a dead path.

Root cause: set_non_binding treated non_binding=False (unwrap) as an immediate error and
hard-DELETED the paragraph on wrap, so a wrapped block could never be restored. The fix toggles a
binding flag (keeping the row), making wrap -> unwrap a byte-identical round-trip.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from plan_manager.hrs import paragraphs
from plan_manager.domain.paragraph_store import StoredParagraph


PLAN = uuid.uuid4()


class _FakeParagraphStore:
    """In-memory stand-in for domain.paragraph_store keyed by position."""

    def __init__(self, rows: list[StoredParagraph]):
        self.rows = {row.uuid: row for row in rows}

    def get_paragraph_at_position(self, conn, plan_uuid, position, *, binding):
        for row in self.rows.values():
            if row.position == position and row.binding == binding:
                return row
        return None

    def set_paragraph_binding(self, conn, row_uuid, binding):
        self.rows[row_uuid].binding = binding


@pytest.fixture()
def wired(monkeypatch):
    row = StoredParagraph(
        uuid=uuid.uuid4(), plan_uuid=PLAN, label="a1b2", text="binding text", position=4, binding=True
    )
    fake = _FakeParagraphStore([row])
    monkeypatch.setattr(paragraphs, "paragraph_store", fake)
    monkeypatch.setattr(paragraphs, "get_plan", lambda conn, plan_uuid: SimpleNamespace(head_revision_uuid=None))
    monkeypatch.setattr(paragraphs, "record_revision", lambda *a, **k: uuid.uuid4())
    return fake, row


def test_wrap_then_unwrap_round_trip_restores_binding(wired) -> None:
    fake, row = wired

    paragraphs.set_non_binding(object(), PLAN, 4, non_binding=True, author="api", cascade=None)
    assert fake.rows[row.uuid].binding is False  # wrapped: row kept, hidden from listing

    paragraphs.set_non_binding(object(), PLAN, 4, non_binding=False, author="api", cascade=None)
    assert fake.rows[row.uuid].binding is True  # unwrapped: restored, same text
    assert fake.rows[row.uuid].text == "binding text"


def test_unwrap_with_no_wrapped_block_raises(wired) -> None:
    # Nothing has been wrapped at position 4, so there is no non-binding row to restore.
    with pytest.raises(ValueError):
        paragraphs.set_non_binding(object(), PLAN, 4, non_binding=False, author="api", cascade=None)


def test_wrap_with_no_binding_block_raises(wired) -> None:
    with pytest.raises(ValueError):
        paragraphs.set_non_binding(object(), PLAN, 99, non_binding=True, author="api", cascade=None)


# --- version-graph round-trip (verifier defect: binding must survive cascade restore) ---

def test_wrap_snapshot_is_binding_state_change_not_deletion(wired, monkeypatch) -> None:
    """A wrap must be recorded as binding=False (row kept), never as deleted=True,
    so cascade abort restores the flag instead of hard-deleting the kept row."""
    fake, row = wired
    recorded: list[dict] = []

    def _capture_revision(conn, plan_uuid, author, message, changes, parent, ref_name=None):
        recorded.extend(snapshot for _uuid, snapshot in changes)
        return uuid.uuid4()

    monkeypatch.setattr(paragraphs, "record_revision", _capture_revision)

    paragraphs.set_non_binding(object(), PLAN, 4, non_binding=True, author="api", cascade=None)
    paragraphs.set_non_binding(object(), PLAN, 4, non_binding=False, author="api", cascade=None)

    wrap_snap, unwrap_snap = recorded
    assert wrap_snap["binding"] is False
    assert "deleted" not in wrap_snap
    assert unwrap_snap["binding"] is True
    assert wrap_snap["text"] == unwrap_snap["text"] == "binding text"


def test_apply_snapshot_restores_binding_flag() -> None:
    """cascade abort/restore must write the snapshot's binding flag back to the row,
    defaulting to True for historical snapshots recorded before the flag existed."""
    from plan_manager.cascade.restore import apply_snapshot

    executed: list[tuple[str, tuple]] = []

    class _Conn:
        def execute(self, sql, params):
            executed.append((sql, params))

    node = uuid.uuid4()
    base = {
        "kind": "paragraph",
        "plan_uuid": str(PLAN),
        "label": "a1b2",
        "text": "t",
        "position": 4,
    }

    apply_snapshot(_Conn(), node, {**base, "binding": False})
    apply_snapshot(_Conn(), node, {**base, "binding": True})
    apply_snapshot(_Conn(), node, base)  # historical snapshot without the flag

    for (sql, params), expected in zip(executed, (False, True, True)):
        assert "binding = EXCLUDED.binding" in sql
        assert params[-1] is expected
