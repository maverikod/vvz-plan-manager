"""Audit-trail and not-found coverage for the four bug-family hard_delete_*
wrappers added to plan_manager/storage/runtime_hard_delete.py (todo 9b09c9b0,
full CRUD for the bug family): hard_delete_bug, hard_delete_bug_impact,
hard_delete_bug_fix, hard_delete_bug_fix_propagation.

Each wrapper is a thin audited layer over DataclassEntity.crud_get/
crud_hard_delete (physical deletion and the inbound-reference admission check
both live in plan_manager.domain.entity, already covered by the command-level
DELETE_BLOCKED tests in tests/test_bug_*_delete_command.py). These tests
verify, in isolation, that each wrapper: (1) raises the documented
DomainCommandError NOT_FOUND code when crud_get finds no row; (2) otherwise
calls crud_hard_delete with require_soft_deleted=False; and (3) records
exactly one hard_delete audit entry via record_runtime_change with the
correct entity_type, entity_id, action, changed_by, and the plan_uuid derived
from that entity's own row (or None where the entity carries no plan_uuid of
its own, per bug_fix's documented convention).
"""
from __future__ import annotations

import uuid
from typing import Any

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.commands.errors import DomainCommandError
from plan_manager.storage import runtime_hard_delete


def _install_audit_spy(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def _fake_record_runtime_change(conn, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(runtime_hard_delete, "record_runtime_change", _fake_record_runtime_change)
    return calls


def test_hard_delete_bug_not_found_raises_bug_not_found(monkeypatch) -> None:
    bug_uuid = uuid.uuid4()
    monkeypatch.setattr(BugReport, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: None))

    try:
        runtime_hard_delete.hard_delete_bug(conn=object(), bug_uuid=bug_uuid, changed_by="tester")
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "BUG_NOT_FOUND"


def test_hard_delete_bug_records_hard_delete_audit_with_source_plan_uuid(monkeypatch) -> None:
    bug_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    calls = _install_audit_spy(monkeypatch)
    hard_delete_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        BugReport,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "source_plan_uuid": plan_uuid}),
    )
    monkeypatch.setattr(
        BugReport,
        "crud_hard_delete",
        classmethod(
            lambda cls, conn, entity_id, **kw: hard_delete_calls.append({"entity_id": entity_id, **kw})
        ),
    )

    runtime_hard_delete.hard_delete_bug(conn=object(), bug_uuid=bug_uuid, changed_by="tester")

    assert hard_delete_calls == [{"entity_id": bug_uuid, "returning": False, "require_soft_deleted": False}]
    assert calls == [
        {
            "plan_uuid": plan_uuid,
            "entity_type": "bug_report",
            "entity_id": bug_uuid,
            "action": "hard_delete",
            "changed_by": "tester",
        }
    ]


def test_hard_delete_bug_impact_not_found_raises_bug_impact_not_found(monkeypatch) -> None:
    impact_uuid = uuid.uuid4()
    monkeypatch.setattr(BugImpact, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: None))

    try:
        runtime_hard_delete.hard_delete_bug_impact(conn=object(), impact_uuid=impact_uuid, changed_by="tester")
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "BUG_IMPACT_NOT_FOUND"


def test_hard_delete_bug_impact_records_hard_delete_audit_with_target_plan_uuid(monkeypatch) -> None:
    impact_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    calls = _install_audit_spy(monkeypatch)
    monkeypatch.setattr(
        BugImpact,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "target_plan_uuid": plan_uuid}),
    )
    monkeypatch.setattr(BugImpact, "crud_hard_delete", classmethod(lambda cls, conn, entity_id, **kw: None))

    runtime_hard_delete.hard_delete_bug_impact(conn=object(), impact_uuid=impact_uuid, changed_by="tester")

    assert calls == [
        {
            "plan_uuid": plan_uuid,
            "entity_type": "bug_impact",
            "entity_id": impact_uuid,
            "action": "hard_delete",
            "changed_by": "tester",
        }
    ]


def test_hard_delete_bug_fix_not_found_raises_bug_fix_not_found(monkeypatch) -> None:
    fix_uuid = uuid.uuid4()
    monkeypatch.setattr(BugFix, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: None))

    try:
        runtime_hard_delete.hard_delete_bug_fix(conn=object(), fix_uuid=fix_uuid, changed_by="tester")
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "BUG_FIX_NOT_FOUND"


def test_hard_delete_bug_fix_records_hard_delete_audit_with_none_plan_uuid(monkeypatch) -> None:
    """BugFix carries no plan_uuid field of its own; the wrapper always records
    plan_uuid=None, matching the convention used by every other bug_fix_store
    mutation (create/update/soft_delete)."""
    fix_uuid = uuid.uuid4()
    calls = _install_audit_spy(monkeypatch)
    monkeypatch.setattr(
        BugFix, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "bug_uuid": uuid.uuid4()})
    )
    monkeypatch.setattr(BugFix, "crud_hard_delete", classmethod(lambda cls, conn, entity_id, **kw: None))

    runtime_hard_delete.hard_delete_bug_fix(conn=object(), fix_uuid=fix_uuid, changed_by="tester")

    assert calls == [
        {
            "plan_uuid": None,
            "entity_type": "bug_fix",
            "entity_id": fix_uuid,
            "action": "hard_delete",
            "changed_by": "tester",
        }
    ]


def test_hard_delete_bug_fix_propagation_not_found_raises_bug_propagation_not_found(monkeypatch) -> None:
    propagation_uuid = uuid.uuid4()
    monkeypatch.setattr(BugFixPropagation, "crud_get", classmethod(lambda cls, conn, entity_id, **kw: None))

    try:
        runtime_hard_delete.hard_delete_bug_fix_propagation(
            conn=object(), propagation_uuid=propagation_uuid, changed_by="tester"
        )
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "BUG_PROPAGATION_NOT_FOUND"


def test_hard_delete_bug_fix_propagation_records_hard_delete_audit_with_linked_plan_uuid(monkeypatch) -> None:
    propagation_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    calls = _install_audit_spy(monkeypatch)
    monkeypatch.setattr(
        BugFixPropagation,
        "crud_get",
        classmethod(lambda cls, conn, entity_id, **kw: {"uuid": entity_id, "linked_plan_uuid": plan_uuid}),
    )
    monkeypatch.setattr(
        BugFixPropagation, "crud_hard_delete", classmethod(lambda cls, conn, entity_id, **kw: None)
    )

    runtime_hard_delete.hard_delete_bug_fix_propagation(
        conn=object(), propagation_uuid=propagation_uuid, changed_by="tester"
    )

    assert calls == [
        {
            "plan_uuid": plan_uuid,
            "entity_type": "bug_fix_propagation",
            "entity_id": propagation_uuid,
            "action": "hard_delete",
            "changed_by": "tester",
        }
    ]
