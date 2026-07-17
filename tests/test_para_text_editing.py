"""Tests for targeted HRS text editing (para_insert / para_update / para_delete, 0.1.40).

Domain-level tests exercise the orchestration in
plan_manager.hrs.paragraph_edit
against an in-memory stand-in for domain.paragraph_store (the established
monkeypatch style of tests/test_para_mark_non_binding_unwrap.py), asserting
the position-space invariant: the stored position column is ONE sequence over
ALL rows (binding and wrapped non-binding), so inserts/deletes shift
non-binding rows too. Command-level tests exercise the admission triage
(FROZEN_ARTIFACT / CASCADE_CONFLICT / CASCADE_REQUIRED) with the established
fake-db pattern of tests/test_step_create_admission_guard.py.
"""
from __future__ import annotations

import asyncio
import dataclasses
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from plan_manager.cascade.record import CascadeError
from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain.paragraph_store import StoredParagraph
from plan_manager.hrs import paragraph_edit as paragraphs


PLAN = uuid.uuid4()


class _FakeParagraphStore:
    """In-memory stand-in for domain.paragraph_store."""

    StoredParagraph = StoredParagraph

    def __init__(self, rows: list[StoredParagraph]):
        self.rows: dict[uuid.UUID, StoredParagraph] = {row.uuid: row for row in rows}

    def _ordered(self) -> list[StoredParagraph]:
        return sorted(self.rows.values(), key=lambda row: row.position)

    def list_paragraphs(self, conn, plan_uuid):
        # Detached copies, like the real store's freshly-built dataclasses:
        # a later shift_positions must not retroactively mutate a listing.
        return [dataclasses.replace(row) for row in self._ordered() if row.binding]

    def list_all_paragraphs(self, conn, plan_uuid):
        return [dataclasses.replace(row) for row in self._ordered()]

    def get_paragraph_at_position(self, conn, plan_uuid, position, *, binding):
        for row in self.rows.values():
            if row.position == position and row.binding == binding:
                return row
        return None

    def set_paragraph_binding(self, conn, row_uuid, binding):
        self.rows[row_uuid].binding = binding

    def insert_paragraph_at(self, conn, plan_uuid, label, text, position):
        row_uuid = uuid.uuid4()
        self.rows[row_uuid] = StoredParagraph(
            uuid=row_uuid, plan_uuid=plan_uuid, label=label,
            text=text, position=position, binding=True,
        )
        return row_uuid

    def update_paragraph_text(self, conn, row_uuid, text):
        self.rows[row_uuid].text = text

    def delete_paragraph(self, conn, row_uuid):
        del self.rows[row_uuid]

    def shift_positions(self, conn, plan_uuid, start_position, delta):
        for row in self.rows.values():
            if row.position >= start_position:
                row.position += delta


def _row(label: str, text: str, position: int, binding: bool = True) -> StoredParagraph:
    return StoredParagraph(
        uuid=uuid.uuid4(), plan_uuid=PLAN, label=label,
        text=text, position=position, binding=binding,
    )


@pytest.fixture()
def wired(monkeypatch):
    """Three binding rows at 0/1/3 with a wrapped non-binding row at 2."""
    rows = [
        _row("aaa0", "first", 0),
        _row("bbb1", "second", 1),
        _row("cccc", "wrapped", 2, binding=False),
        _row("ddd3", "third", 3),
    ]
    fake = _FakeParagraphStore(rows)
    recorded: list[tuple[str, list[dict]]] = []

    def _capture_revision(conn, plan_uuid, author, message, changes, parent, ref_name=None):
        recorded.append((message, [snapshot for _uuid, snapshot in changes]))
        return uuid.uuid4()

    monkeypatch.setattr(paragraphs, "paragraph_store", fake)
    monkeypatch.setattr(
        paragraphs, "get_plan",
        lambda conn, plan_uuid: SimpleNamespace(head_revision_uuid=None),
    )
    monkeypatch.setattr(paragraphs, "record_revision", _capture_revision)
    return fake, recorded


def _positions(fake: _FakeParagraphStore) -> list[tuple[str, int, bool]]:
    return [(row.label, row.position, row.binding) for row in fake._ordered()]


# --- para_insert domain behavior ---

def test_insert_at_head_shifts_every_row_including_non_binding(wired) -> None:
    fake, recorded = wired
    result = paragraphs.insert_paragraph(
        object(), PLAN, "new head", 0, "eee4", "api", None
    )
    assert result["position"] == 0
    assert _positions(fake) == [
        ("eee4", 0, True), ("aaa0", 1, True), ("bbb1", 2, True),
        ("cccc", 3, False), ("ddd3", 4, True),
    ]
    # One revision: the new row plus every shifted row, non-binding included.
    message, snapshots = recorded[0]
    assert message == "insert paragraph eee4"
    assert {snap["label"] for snap in snapshots} == {"eee4", "aaa0", "bbb1", "cccc", "ddd3"}
    wrapped = next(snap for snap in snapshots if snap["label"] == "cccc")
    assert wrapped["binding"] is False and wrapped["position"] == 3


def test_insert_in_middle_maps_binding_index_to_physical_position(wired) -> None:
    fake, _recorded = wired
    # Binding order is aaa0, bbb1, ddd3; binding index 2 addresses ddd3 at
    # PHYSICAL position 3 (the wrapped row at 2 is skipped by the index but
    # shifted by the insert).
    result = paragraphs.insert_paragraph(
        object(), PLAN, "before third", 2, None, "api", None
    )
    assert result["position"] == 3
    assert _positions(fake) == [
        ("aaa0", 0, True), ("bbb1", 1, True), ("cccc", 2, False),
        (result["label"], 3, True), ("ddd3", 4, True),
    ]


def test_insert_append_omitted_position_lands_after_all_rows(wired) -> None:
    fake, recorded = wired
    result = paragraphs.insert_paragraph(
        object(), PLAN, "appended", None, None, "api", None
    )
    assert result["position"] == 4
    assert _positions(fake)[-1] == (result["label"], 4, True)
    # Append shifts nothing: the revision carries only the new row.
    assert len(recorded[0][1]) == 1


def test_insert_position_equal_to_binding_count_appends(wired) -> None:
    fake, _recorded = wired
    result = paragraphs.insert_paragraph(
        object(), PLAN, "appended", 3, None, "api", None
    )
    assert result["position"] == 4


def test_insert_position_out_of_range_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(object(), PLAN, "x", 4, None, "api", None)
    assert exc_info.value.code == "IMPORT_INVALID"


def test_insert_auto_label_is_fresh_four_char_base36(wired) -> None:
    fake, _recorded = wired
    result = paragraphs.insert_paragraph(object(), PLAN, "auto", None, None, "api", None)
    assert paragraphs._LABEL_RE.match(result["label"])
    assert result["label"] not in {"aaa0", "bbb1", "cccc", "ddd3"}


def test_insert_duplicate_label_rejected_even_against_non_binding_row(wired) -> None:
    # "cccc" is held by the WRAPPED row: still not reusable (unwrap restores it).
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(object(), PLAN, "x", None, "cccc", "api", None)
    assert exc_info.value.code == "DUPLICATE_ID"


def test_insert_bad_label_format_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(object(), PLAN, "x", None, "TOOLONG!", "api", None)
    assert exc_info.value.code == "IMPORT_INVALID"


def test_insert_text_label_prefix_supplies_the_label(wired) -> None:
    fake, _recorded = wired
    result = paragraphs.insert_paragraph(
        object(), PLAN, "{eee4} prefixed text", None, None, "api", None
    )
    assert result["label"] == "eee4"
    assert result["text"] == "prefixed text"  # prefix stripped before storage


def test_insert_text_prefix_conflicting_with_label_param_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(
            object(), PLAN, "{eee4} text", None, "fff5", "api", None
        )
    assert exc_info.value.code == "IMPORT_INVALID"


def test_insert_multi_paragraph_text_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(
            object(), PLAN, "first block\n\nsecond block", None, None, "api", None
        )
    assert exc_info.value.code == "IMPORT_INVALID"


def test_insert_empty_text_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.insert_paragraph(object(), PLAN, "# heading only", None, None, "api", None)
    assert exc_info.value.code == "IMPORT_INVALID"


def test_insert_cascade_mode_records_one_multi_node_revision(wired, monkeypatch) -> None:
    fake, recorded = wired
    cascade_calls: list[list[dict]] = []

    def _capture_many(conn, plan_uuid, cascade, node_changes, status_updates, author, message):
        cascade_calls.append([snapshot for _uuid, snapshot in node_changes])
        return uuid.uuid4()

    monkeypatch.setattr(paragraphs, "cascade_write_many", _capture_many)

    paragraphs.insert_paragraph(
        object(), PLAN, "cascaded", 0, None, "api", SimpleNamespace(name="cascade/x")
    )
    assert not recorded  # direct-mode record_revision must NOT run
    assert len(cascade_calls) == 1
    assert len(cascade_calls[0]) == 5  # new row + four shifted rows


# --- para_update domain behavior ---

def test_update_replaces_text_preserving_uuid_position_label(wired) -> None:
    fake, recorded = wired
    before = next(row for row in fake.rows.values() if row.label == "bbb1")
    result = paragraphs.update_paragraph(
        object(), PLAN, "bbb1", "second, revised", "api", None
    )
    after = fake.rows[before.uuid]
    assert result["uuid"] == before.uuid
    assert after.text == "second, revised"
    assert after.label == "bbb1" and after.position == 1 and after.binding is True
    message, snapshots = recorded[0]
    assert message == "update paragraph bbb1"
    assert snapshots == [
        {
            "kind": "paragraph", "uuid": str(before.uuid), "plan_uuid": str(PLAN),
            "label": "bbb1", "text": "second, revised", "position": 1, "binding": True,
        }
    ]


def test_update_accepts_text_prefix_equal_to_addressed_label(wired) -> None:
    fake, _recorded = wired
    result = paragraphs.update_paragraph(
        object(), PLAN, "bbb1", "{bbb1} revised", "api", None
    )
    assert result["text"] == "revised"


def test_update_rejects_text_prefix_with_different_label(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.update_paragraph(object(), PLAN, "bbb1", "{zzz9} revised", "api", None)
    assert exc_info.value.code == "IMPORT_INVALID"


def test_update_multi_paragraph_text_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.update_paragraph(object(), PLAN, "bbb1", "one\n\ntwo", "api", None)
    assert exc_info.value.code == "IMPORT_INVALID"


def test_update_unknown_label_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.update_paragraph(object(), PLAN, "zzz9", "text", "api", None)
    assert exc_info.value.code == "PARAGRAPH_NOT_FOUND"


def test_update_cannot_address_non_binding_row(wired) -> None:
    # "cccc" exists but is wrapped: label addressing covers binding rows only.
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.update_paragraph(object(), PLAN, "cccc", "text", "api", None)
    assert exc_info.value.code == "PARAGRAPH_NOT_FOUND"


# --- para_delete domain behavior ---

def test_delete_removes_row_and_closes_the_gap_across_non_binding(wired) -> None:
    fake, recorded = wired
    result = paragraphs.delete_paragraph(object(), PLAN, "bbb1", "api", None)
    assert result["position"] == 1
    assert _positions(fake) == [
        ("aaa0", 0, True), ("cccc", 1, False), ("ddd3", 2, True),
    ]
    message, snapshots = recorded[0]
    assert message == "delete paragraph bbb1"
    tombstone = next(snap for snap in snapshots if snap["label"] == "bbb1")
    assert tombstone["deleted"] is True  # true removal, unlike a wrap
    shifted = {snap["label"]: snap["position"] for snap in snapshots if snap["label"] != "bbb1"}
    assert shifted == {"cccc": 1, "ddd3": 2}


def test_delete_unknown_label_rejected(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.delete_paragraph(object(), PLAN, "zzz9", "api", None)
    assert exc_info.value.code == "PARAGRAPH_NOT_FOUND"


def test_delete_cannot_address_non_binding_row(wired) -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        paragraphs.delete_paragraph(object(), PLAN, "cccc", "api", None)
    assert exc_info.value.code == "PARAGRAPH_NOT_FOUND"


# --- command-level admission triage (mirrors sibling frozen-guard tests) ---

from plan_manager.commands import (  # noqa: E402  (import placed near its tests)
    para_delete_command,
    para_insert_command,
    para_update_command,
)
from plan_manager.commands.para_delete_command import ParaDeleteCommand  # noqa: E402
from plan_manager.commands.para_insert_command import ParaInsertCommand  # noqa: E402
from plan_manager.commands.para_update_command import ParaUpdateCommand  # noqa: E402


@contextmanager
def _fake_db():
    yield object()


_CASES = [
    (para_insert_command, ParaInsertCommand, {"plan": "p", "text": "t"}),
    (para_update_command, ParaUpdateCommand, {"plan": "p", "label": "aaa0", "text": "t"}),
    (para_delete_command, ParaDeleteCommand, {"plan": "p", "label": "aaa0"}),
]


def _patch_admission(monkeypatch, module, *, frozen: bool, admit: bool):
    monkeypatch.setattr(module, "db_connection", _fake_db)
    monkeypatch.setattr(
        module, "resolve_plan",
        lambda conn, plan: SimpleNamespace(uuid=PLAN),
    )
    if admit:
        monkeypatch.setattr(
            module, "check_admission",
            lambda conn, plan_uuid, kind, target_uuid, cascade_uuid: None,
        )
    else:
        def _reject(conn, plan_uuid, kind, target_uuid, cascade_uuid):
            raise CascadeError("admission rejected")
        monkeypatch.setattr(module, "check_admission", _reject)
    step = SimpleNamespace(status="frozen" if frozen else "draft")
    monkeypatch.setattr(module, "load_steps", lambda conn, plan_uuid: {uuid.uuid4(): step})


@pytest.mark.parametrize("module,command,params", _CASES)
def test_frozen_plan_direct_mutation_rejected(monkeypatch, module, command, params) -> None:
    _patch_admission(monkeypatch, module, frozen=True, admit=False)
    payload = asyncio.run(command().execute(**params)).to_dict()
    assert payload["error"]["data"]["domain_code"] == "FROZEN_ARTIFACT"


@pytest.mark.parametrize("module,command,params", _CASES)
def test_unfrozen_plan_without_cascade_gets_cascade_required(monkeypatch, module, command, params) -> None:
    _patch_admission(monkeypatch, module, frozen=False, admit=False)
    payload = asyncio.run(command().execute(**params)).to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"


@pytest.mark.parametrize("module,command,params", _CASES)
def test_stale_cascade_uuid_gets_cascade_conflict(monkeypatch, module, command, params) -> None:
    _patch_admission(monkeypatch, module, frozen=True, admit=False)
    payload = asyncio.run(
        command().execute(**params, cascade_uuid=str(uuid.uuid4()))
    ).to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"


def test_para_insert_admitted_path_verifies_and_returns_created_row(monkeypatch) -> None:
    _patch_admission(monkeypatch, para_insert_command, frozen=False, admit=True)
    row_uuid = uuid.uuid4()
    created = {"uuid": row_uuid, "label": "eee4", "position": 0, "text": "t"}
    monkeypatch.setattr(
        para_insert_command, "insert_paragraph",
        lambda conn, plan_uuid, text, position, label, author, cascade: created,
    )
    stored = StoredParagraph(
        uuid=row_uuid, plan_uuid=PLAN, label="eee4", text="t", position=0, binding=True,
    )
    monkeypatch.setattr(
        para_insert_command.paragraph_store, "list_paragraphs",
        lambda conn, plan_uuid: [stored],
    )
    payload = asyncio.run(ParaInsertCommand().execute(plan="p", text="t")).to_dict()
    assert payload["success"] is True
    assert payload["data"] == {"uuid": str(row_uuid), "label": "eee4", "position": 0}


def test_para_delete_admitted_path_verifies_removal(monkeypatch) -> None:
    _patch_admission(monkeypatch, para_delete_command, frozen=False, admit=True)
    row_uuid = uuid.uuid4()
    monkeypatch.setattr(
        para_delete_command, "delete_paragraph",
        lambda conn, plan_uuid, label, author, cascade: {
            "uuid": row_uuid, "label": label, "position": 1,
        },
    )
    monkeypatch.setattr(
        para_delete_command.paragraph_store, "list_all_paragraphs",
        lambda conn, plan_uuid: [],
    )
    payload = asyncio.run(ParaDeleteCommand().execute(plan="p", label="aaa0")).to_dict()
    assert payload["success"] is True
    assert payload["data"]["deleted"] is True
