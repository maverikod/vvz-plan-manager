"""Regression tests for bug 82832a18: a shared terminal-status guard governs all bug transition
commands. closed/rejected/duplicate are left ONLY via bug_reopen; bug_confirm is legal only from
reported/triaged; every refusal is INVALID_RUNTIME_STATUS_TRANSITION with legal_targets."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands import (
    bug_close_command,
    bug_confirm_command,
    bug_mark_duplicate_command,
    bug_reject_command,
    bug_reopen_command,
)
from plan_manager.domain.bug_status_transitions import (
    BugStatusTransitionError,
    COMMAND_TARGET,
    TERMINAL_STATUSES,
    guard_bug_transition,
    legal_targets,
)

TERMINAL = sorted(TERMINAL_STATUSES)
TRANSITION_COMMANDS = sorted(COMMAND_TARGET)


@pytest.mark.parametrize("status", TERMINAL)
@pytest.mark.parametrize("command", TRANSITION_COMMANDS)
def test_terminal_status_left_only_by_reopen(command: str, status: str) -> None:
    if command == "bug_reopen":
        guard_bug_transition(command, status)  # legal: no raise
        return
    with pytest.raises(BugStatusTransitionError) as excinfo:
        guard_bug_transition(command, status)
    assert excinfo.value.current_status == status
    assert excinfo.value.legal_targets == ["reopened"]


def test_confirm_legal_only_from_reported_triaged_confirmed() -> None:
    for status in ("reported", "triaged", "confirmed"):
        guard_bug_transition("bug_confirm", status)  # no raise
    for status in ("fixing", "verified", "reopened"):
        with pytest.raises(BugStatusTransitionError):
            guard_bug_transition("bug_confirm", status)


def test_legal_targets_from_terminal_is_reopened_only() -> None:
    assert legal_targets("closed") == ["reopened"]
    assert legal_targets("rejected") == ["reopened"]
    assert legal_targets("duplicate") == ["reopened"]


def test_legal_targets_from_confirmed_lists_reachable_commands() -> None:
    assert legal_targets("confirmed") == ["closed", "confirmed", "duplicate", "rejected"]


# --- command-surface wiring -------------------------------------------------

@contextmanager
def _fake_db():
    yield object()


class _Bug:
    def __init__(self, status: str):
        self.status = status

    def to_payload(self) -> dict:
        return {"status": self.status}


def _dummy_plan(conn, plan):
    class _P:
        uuid = uuid.uuid4()
    return _P()


def test_reject_on_closed_bug_returns_domain_transition_error(monkeypatch) -> None:
    monkeypatch.setattr(bug_reject_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_reject_command, "resolve_plan", _dummy_plan)
    monkeypatch.setattr(bug_reject_command, "get_bug", lambda conn, u: _Bug("closed"))
    monkeypatch.setattr(
        bug_reject_command, "set_bug_status",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not mutate")),
    )

    result = asyncio.run(
        bug_reject_command.BugRejectCommand().execute(
            plan="p", bug_id=str(uuid.uuid4()), changed_by="alice"
        )
    )
    data = result.to_dict()["error"]["data"]
    assert data["domain_code"] == "INVALID_RUNTIME_STATUS_TRANSITION"
    assert data["legal_targets"] == ["reopened"]
    assert data["current_status"] == "closed"


def test_reopen_on_closed_bug_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr(bug_reopen_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_reopen_command, "resolve_plan", _dummy_plan)
    monkeypatch.setattr(bug_reopen_command, "get_bug", lambda conn, u: _Bug("closed"))
    monkeypatch.setattr(
        bug_reopen_command, "set_bug_status", lambda *a, **k: _Bug("reopened")
    )

    result = asyncio.run(
        bug_reopen_command.BugReopenCommand().execute(
            plan="p", bug_id=str(uuid.uuid4()), changed_by="alice"
        )
    )
    assert result.to_dict()["data"]["status"] == "reopened"
