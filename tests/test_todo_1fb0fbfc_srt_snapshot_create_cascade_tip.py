"""Regression tests for todo 1fb0fbfc: srt_snapshot_create must support
snapshotting the open cascade's current WORKING TIP, not silently record the
committed head revision.

Observed defect: an open cascade had base committed revision
2ef5f739-c44c-4600-929f-2956770e384e and working tip
20210f5d-9f0d-4aa3-b47c-8bf28e96da6b; calling srt_snapshot_create without a
cascade/revision selector recorded the snapshot at the BASE committed
revision instead of the working tip.

Fix: srt_snapshot_create now accepts optional revision/cascade_uuid
selectors, resolved via the SAME resolve_context_revision() the
context-block commands already use (mutually-exclusive validation,
CASCADE_CONFLICT / REVISION_NOT_FOUND on misuse); the recorded
revision_uuid is the ACTUAL resolved revision (cascade working tip when
cascade_uuid is supplied, unchanged committed-head default otherwise). The
tree_content computation itself is untouched (it always read the live step
table; this fix only corrects the revision_uuid metadata recorded
alongside it and adds explicit, validated selectors) -- srt_diff (keyed
purely by caller-supplied snapshot_uuid, diffing tree_content) and frozen-
truth semantics (srt_snapshot_create only ever writes a derived, non-plan-
truth record) are unaffected.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import srt_snapshot_create_command
from plan_manager.commands.srt_snapshot_create_command import SrtSnapshotCreateCommand
from plan_manager.domain.plan import Plan
from plan_manager.views.context_blocks import ContextRevision


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000401")
HEAD_UUID = uuid.UUID("00000000-0000-0000-0000-000000000402")
BASE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000403")
TIP_UUID = uuid.UUID("00000000-0000-0000-0000-000000000404")
CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000405")


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="srt-create-plan",
        status="draft",
        context_budget=4000,
        head_revision_uuid=HEAD_UUID,
        project_ids=[],
        primary_project_id=None,
    )


def _cascade() -> CascadeRecord:
    return CascadeRecord(
        uuid=CASCADE_UUID,
        plan_uuid=PLAN_UUID,
        name=f"cascade/{CASCADE_UUID}",
        base_revision_uuid=BASE_UUID,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


class _FakeTree:
    pass


def _patch_common(monkeypatch):
    @contextmanager
    def fake_db_connection():
        yield object()

    class Config:
        embedding_url = "http://embed"
        embedding_timeout = 5.0

    monkeypatch.setattr(srt_snapshot_create_command, "db_connection", fake_db_connection)
    monkeypatch.setattr(srt_snapshot_create_command, "resolve_plan", lambda _conn, _plan_name: _plan())
    monkeypatch.setattr(srt_snapshot_create_command, "app_config", lambda: Config())
    monkeypatch.setattr(srt_snapshot_create_command, "assemble_reproduction_input", lambda _conn, _plan_uuid, _url, timeout=None: (object(), lambda text: [0.0]))
    monkeypatch.setattr(srt_snapshot_create_command, "warm_embedding_cache", lambda *a, **k: None)
    monkeypatch.setattr(srt_snapshot_create_command, "build_tree", lambda *a, **k: _FakeTree())
    monkeypatch.setattr(dataclasses, "asdict", lambda _tree: {"root": "content"})

    captured: dict = {}

    def fake_insert(conn, plan_uuid, revision_uuid, algorithm_version, summarizer_version, embedding_model, tree_content):
        captured["revision_uuid"] = revision_uuid

        class _Rec:
            def to_payload(self_inner):
                return {
                    "uuid": "snap-uuid",
                    "plan_uuid": str(plan_uuid),
                    "revision_uuid": str(revision_uuid),
                    "tree_hash": "hash123",
                }

        return _Rec()

    monkeypatch.setattr(srt_snapshot_create_command, "insert_srt_snapshot", fake_insert)
    return captured


def _kwargs(**overrides):
    base = {
        "plan": "srt-create-plan",
        "algorithm_version": "1.0.0",
        "summarizer_version": "1.0.0",
        "embedding_model": "text-embedding-3-small",
    }
    base.update(overrides)
    return base


def test_default_no_selector_records_committed_head_unchanged(monkeypatch):
    """Backward-compatible default: no revision/cascade_uuid -> committed head, as before."""
    captured = _patch_common(monkeypatch)
    monkeypatch.setattr(srt_snapshot_create_command, "resolve_context_revision", lambda _conn, _plan, revision=None, cascade_uuid=None: ContextRevision(HEAD_UUID, None))

    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs()))
    data = result.to_dict()["data"]

    assert captured["revision_uuid"] == HEAD_UUID
    assert data["revision_uuid"] == str(HEAD_UUID)
    assert data["cascade_uuid"] is None
    assert data["snapshot_mode"] == "committed_head"


def test_cascade_uuid_selector_records_the_working_tip_not_base(monkeypatch):
    """The observed defect, fixed: cascade_uuid selects the cascade's working TIP."""
    captured = _patch_common(monkeypatch)
    monkeypatch.setattr(
        srt_snapshot_create_command,
        "resolve_context_revision",
        lambda _conn, _plan, revision=None, cascade_uuid=None: ContextRevision(TIP_UUID, CASCADE_UUID),
    )

    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs(cascade_uuid=str(CASCADE_UUID))))
    data = result.to_dict()["data"]

    assert captured["revision_uuid"] == TIP_UUID
    assert captured["revision_uuid"] != BASE_UUID
    assert data["revision_uuid"] == str(TIP_UUID)
    assert data["cascade_uuid"] == str(CASCADE_UUID)
    assert data["snapshot_mode"] == "cascade_tip"


def test_explicit_revision_equal_to_head_is_accepted(monkeypatch):
    captured = _patch_common(monkeypatch)
    monkeypatch.setattr(
        srt_snapshot_create_command,
        "resolve_context_revision",
        lambda _conn, _plan, revision=None, cascade_uuid=None: ContextRevision(HEAD_UUID, None),
    )

    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs(revision=str(HEAD_UUID))))
    data = result.to_dict()["data"]

    assert captured["revision_uuid"] == HEAD_UUID
    assert data["snapshot_mode"] == "committed_head"


def test_both_revision_and_cascade_uuid_surface_cascade_conflict(monkeypatch):
    from plan_manager.commands.errors import DomainCommandError

    _patch_common(monkeypatch)

    def _raise(_conn, _plan, revision=None, cascade_uuid=None):
        raise DomainCommandError("CASCADE_CONFLICT", "revision and cascade_uuid are mutually exclusive")

    monkeypatch.setattr(srt_snapshot_create_command, "resolve_context_revision", _raise)

    result = asyncio.run(
        SrtSnapshotCreateCommand().execute(**_kwargs(revision=str(HEAD_UUID), cascade_uuid=str(CASCADE_UUID)))
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"


def test_mismatched_cascade_uuid_never_silently_falls_back_to_head(monkeypatch):
    """resolve_context_revision itself refuses a cascade_uuid that is not the
    plan's actual open cascade -- proving the command never silently
    substitutes head when a cascade snapshot was explicitly requested."""
    from plan_manager.commands.errors import DomainCommandError

    _patch_common(monkeypatch)

    def _raise(_conn, _plan, revision=None, cascade_uuid=None):
        raise DomainCommandError("CASCADE_CONFLICT", "supplied cascade_uuid is not the plan's open cascade")

    monkeypatch.setattr(srt_snapshot_create_command, "resolve_context_revision", _raise)

    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs(cascade_uuid=str(uuid.uuid4()))))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"


# --------------------------------------------------------------------------
# Deeper integration: exercise the REAL resolve_context_revision (not a
# monkeypatched stand-in) against a fake open-cascade/get_ref pair, so the
# wiring is proven end-to-end, not just that the command calls the function.
# --------------------------------------------------------------------------


def test_real_resolve_context_revision_selects_the_cascade_ref_tip(monkeypatch):
    captured = _patch_common(monkeypatch)

    import plan_manager.views.context_blocks as context_blocks_mod

    monkeypatch.setattr(context_blocks_mod, "get_open_cascade", lambda _conn, _plan_uuid: _cascade())
    monkeypatch.setattr(context_blocks_mod, "get_ref", lambda _conn, _plan_uuid, _name: TIP_UUID)
    # srt_snapshot_create_command imported resolve_context_revision directly;
    # patch it back to the REAL function (undoing nothing -- it already IS
    # the real function unless a prior test in this module patched the
    # command-module binding, which does not affect the shared module object).

    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs(cascade_uuid=str(CASCADE_UUID))))
    data = result.to_dict()["data"]

    assert captured["revision_uuid"] == TIP_UUID
    assert data["cascade_uuid"] == str(CASCADE_UUID)
    assert data["snapshot_mode"] == "cascade_tip"


def test_real_resolve_context_revision_rejects_wrong_cascade_uuid(monkeypatch):
    _patch_common(monkeypatch)

    import plan_manager.views.context_blocks as context_blocks_mod

    monkeypatch.setattr(context_blocks_mod, "get_open_cascade", lambda _conn, _plan_uuid: _cascade())
    monkeypatch.setattr(context_blocks_mod, "get_ref", lambda _conn, _plan_uuid, _name: TIP_UUID)

    other_cascade = uuid.uuid4()
    result = asyncio.run(SrtSnapshotCreateCommand().execute(**_kwargs(cascade_uuid=str(other_cascade))))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"
