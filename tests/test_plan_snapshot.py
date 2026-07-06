import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands.plan_snapshot_command import PlanSnapshotCommand
from plan_manager.domain.plan import Plan
from plan_manager.exchange import exporter


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HEAD_UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")
CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000003")
TIP_UUID = uuid.UUID("00000000-0000-0000-0000-000000000004")


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="snapshot-plan",
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
        base_revision_uuid=HEAD_UUID,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


def test_historical_hrs_render_strips_duplicate_label_prefix() -> None:
    text = exporter.render_hrs_text(
        [
            {
                "label": "a1b2",
                "text": "{a1b2} First requirement.",
                "position": 1,
            },
            {
                "label": "c3d4",
                "text": "Second requirement.",
                "position": 2,
            },
        ]
    )

    assert text.count("{a1b2}") == 1
    assert text == "{a1b2} First requirement.\n\n{c3d4} Second requirement.\n"


def test_historical_hrs_deduplicates_label_entities_by_revision_order() -> None:
    paragraphs = exporter._dedupe_paragraphs_by_label(
        [
            {"label": "a1b2", "text": "Cascade version.", "position": 10},
            {"label": "c3d4", "text": "Other requirement.", "position": 20},
            {"label": "a1b2", "text": "Base version.", "position": 1},
        ]
    )

    assert paragraphs == [
        {"label": "a1b2", "text": "Cascade version.", "position": 10},
        {"label": "c3d4", "text": "Other requirement.", "position": 20},
    ]


def test_working_snapshot_uses_open_cascade_tip(monkeypatch) -> None:
    calls = []

    def fake_export_plan(_conn, plan_uuid, export_root, revision_uuid=None):
        calls.append((plan_uuid, export_root, revision_uuid))
        return {"root": "/tmp/export/snapshot-plan", "files": 2}

    monkeypatch.setattr(exporter, "get_plan", lambda _conn, _plan_uuid: _plan())
    monkeypatch.setattr(exporter, "get_open_cascade", lambda _conn, _plan_uuid: _cascade())
    monkeypatch.setattr(exporter, "get_ref", lambda _conn, _plan_uuid, _name: TIP_UUID)
    monkeypatch.setattr(exporter, "export_plan", fake_export_plan)

    summary = exporter.export_working_snapshot(object(), PLAN_UUID, "/tmp/export")

    assert calls == [(PLAN_UUID, "/tmp/export", TIP_UUID)]
    assert summary["based_on_revision"] == str(HEAD_UUID)
    assert summary["cascade_uuid"] == str(CASCADE_UUID)
    assert summary["snapshot_revision"] == str(TIP_UUID)


def test_plan_snapshot_command_validates_written_layout(monkeypatch) -> None:
    class Config:
        export_root = "/tmp/export"

    @contextmanager
    def fake_db_connection():
        yield object()

    monkeypatch.setattr(
        "plan_manager.commands.plan_snapshot_command.db_connection",
        fake_db_connection,
    )
    monkeypatch.setattr(
        "plan_manager.commands.plan_snapshot_command.app_config",
        lambda: Config(),
    )
    monkeypatch.setattr(
        "plan_manager.commands.plan_snapshot_command.resolve_plan",
        lambda _conn, _plan_name: _plan(),
    )
    monkeypatch.setattr(
        "plan_manager.commands.plan_snapshot_command.export_working_snapshot",
        lambda _conn, _plan_uuid, _export_root: {
            "root": "/tmp/export/snapshot-plan",
            "files": 2,
            "based_on_revision": str(HEAD_UUID),
            "cascade_uuid": str(CASCADE_UUID),
            "snapshot_revision": str(TIP_UUID),
        },
    )
    monkeypatch.setattr(
        "plan_manager.commands.plan_snapshot_command.validate_layout",
        lambda _root: [],
    )

    result = asyncio.run(PlanSnapshotCommand().execute(plan="snapshot-plan"))

    assert result.to_dict() == {
        "success": True,
        "data": {
            "root": "/tmp/export/snapshot-plan",
            "files": 2,
            "based_on_revision": str(HEAD_UUID),
            "cascade_uuid": str(CASCADE_UUID),
            "snapshot_revision": str(TIP_UUID),
            "importable": True,
        },
    }
