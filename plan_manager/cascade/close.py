"""Commit and abort operations closing a cascade (C-016, C-019, C-020)."""

import uuid

import psycopg

from plan_manager.cascade.record import CascadeError, close_cascade, get_open_cascade
from plan_manager.cascade.restore import restore_state
from plan_manager.domain.plan import set_head_revision
from plan_manager.storage.plan_lock import acquire_plan_lock, release_plan_lock
from plan_manager.storage.version_store import delete_ref, get_ref
from plan_manager.verify.gate import Verdict, run_gate


class CommitRefusedError(RuntimeError):
    """Raised when a cascade commit is refused because the gate is red."""


def commit_cascade(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> Verdict:
    """Atomically publish the plan's open cascade when the gate is green.

    Acquires the per-plan advisory lock, resolves the plan's open cascade
    record (raising ``CascadeError("plan has no open cascade")`` when none
    exists), and runs a fresh mechanical gate over the plan. When the gate
    report is not green, raises ``CommitRefusedError`` carrying the total
    finding count summed across all checks in the report, leaving the
    cascade open and the plan unchanged. When the gate report is green,
    resolves the cascade's ref to its tip revision, advances the plan head
    to that revision, marks the cascade record committed, deletes the
    cascade ref, and returns the gate verdict. The per-plan lock is always
    released before returning or raising.

    :param conn: open psycopg 3 database connection.
    :param plan_uuid: uuid of the plan whose open cascade is committed.
    :return: the ``Verdict`` produced by the fresh mechanical gate run.
    :raises CascadeError: when the plan has no open cascade.
    :raises CommitRefusedError: when the fresh gate run is not green.
    """
    acquire_plan_lock(conn, plan_uuid)
    try:
        rec = get_open_cascade(conn, plan_uuid)
        if rec is None:
            raise CascadeError("plan has no open cascade")
        report, verdict = run_gate(conn, plan_uuid)
        if not report.green:
            finding_count = sum(len(c.findings) for c in report.checks)
            raise CommitRefusedError(
                f"commit refused: mechanical gate not green ({finding_count} findings)"
            )
        tip = get_ref(conn, plan_uuid, rec.name)
        set_head_revision(conn, plan_uuid, tip)
        close_cascade(conn, rec.uuid, "committed")
        delete_ref(conn, plan_uuid, rec.name)
        return verdict
    finally:
        release_plan_lock(conn, plan_uuid)


def abort_cascade(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> None:
    """Discard the plan's open cascade without publishing it.

    Acquires the per-plan advisory lock, resolves the plan's open cascade
    record (raising ``CascadeError("plan has no open cascade")`` when none
    exists), restores working rows to the cascade's base-revision state via
    ``restore_state``, deletes the cascade ref, and marks the cascade
    record aborted. The cascade's recorded revisions remain in the
    append-only version store, addressable by revision id, with no ref
    pointing at them; the published plan head is left untouched. The
    per-plan lock is always released before returning or raising.

    :param conn: open psycopg 3 database connection.
    :param plan_uuid: uuid of the plan whose open cascade is aborted.
    :raises CascadeError: when the plan has no open cascade.
    """
    acquire_plan_lock(conn, plan_uuid)
    try:
        rec = get_open_cascade(conn, plan_uuid)
        if rec is None:
            raise CascadeError("plan has no open cascade")
        tip = get_ref(conn, plan_uuid, rec.name)
        restore_state(conn, plan_uuid, rec.base_revision_uuid, tip)
        delete_ref(conn, plan_uuid, rec.name)
        close_cascade(conn, rec.uuid, "aborted")
    finally:
        release_plan_lock(conn, plan_uuid)
