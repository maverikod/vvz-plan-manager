"""Unit coverage for shared runtime work-layer command helpers."""

from __future__ import annotations

import uuid

from plan_manager.commands import runtime_work_command_helpers as helpers


def test_build_primary_anchor_parses_uuid_fields() -> None:
    anchor = helpers.build_primary_anchor(
        anchor_type="step",
        anchor_project_id="11111111-1111-1111-1111-111111111111",
        anchor_plan_uuid="22222222-2222-2222-2222-222222222222",
        anchor_revision_uuid="33333333-3333-3333-3333-333333333333",
        anchor_step_uuid="44444444-4444-4444-4444-444444444444",
        anchor_ref_id="55555555-5555-5555-5555-555555555555",
        anchor_file_path="src/app.py",
        anchor_step_path="G-001/T-001",
    )

    assert anchor.anchor_type == "step"
    assert anchor.project_id == uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert anchor.plan_uuid == uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert anchor.revision_uuid == uuid.UUID("33333333-3333-3333-3333-333333333333")
    assert anchor.step_uuid == uuid.UUID("44444444-4444-4444-4444-444444444444")
    assert anchor.ref_id == uuid.UUID("55555555-5555-5555-5555-555555555555")
    assert anchor.file_path == "src/app.py"
    assert anchor.step_path == "G-001/T-001"


def test_resolve_anchor_scope_resolves_plan_and_uuid_filters(monkeypatch) -> None:
    class _ResolvedPlan:
        uuid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    monkeypatch.setattr(helpers, "resolve_plan", lambda conn, plan: _ResolvedPlan())

    scope = helpers.resolve_anchor_scope(
        object(),
        project="11111111-1111-1111-1111-111111111111",
        anchor_plan="roadmap",
        revision="22222222-2222-2222-2222-222222222222",
        step="33333333-3333-3333-3333-333333333333",
    )

    assert scope.project_uuid == uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert scope.anchor_plan_uuid == uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert scope.revision_uuid == uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert scope.step_uuid == uuid.UUID("33333333-3333-3333-3333-333333333333")
