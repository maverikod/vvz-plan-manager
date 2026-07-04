"""Read-only preview of the plan's open cascade (C-016)."""

import uuid

import psycopg

from plan_manager.cascade.record import CascadeError, get_open_cascade
from plan_manager.storage.version_store import get_ref
from plan_manager.storage.version_ops import diff
from plan_manager.views.dependency_graph import load_steps
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.verify.gate import run_gate
from plan_manager.verify.finding import render_json


def preview_cascade(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict:
    """Return the read-only preview of the plan's open cascade.

    Resolves the plan's open cascade record, computes the accumulated
    change set between the cascade's base revision and its current tip,
    classifies the needs_review blast radius by artifact path, and runs
    the mechanical gate for a verdict and findings report. Performs no
    writes: it records no revision, changes no status, and does not
    move the head.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The UUID identity of the plan whose open cascade is
            previewed.

    Returns:
        A dict with exactly these keys, in this order:
        "cascade_uuid": str -- the open cascade record's UUID.
        "base_revision_uuid": str -- the revision UUID anchored at
            cascade opening.
        "tip_revision_uuid": str -- the current UUID resolved from the
            cascade's ref.
        "change_set": dict -- the diff() result between
            base_revision_uuid and tip_revision_uuid, with keys
            "added", "removed", "changed", each a list of node uuids.
        "needs_review": list[str] -- artifact paths of steps whose
            status equals "needs_review", sorted ascending.
        "gate_green": bool -- whether the mechanical gate run is green.
        "gate_report_json": str -- the machine-checkable JSON rendering
            of the gate findings report.

    Raises:
        CascadeError: if the plan has no open cascade.
    """
    rec = get_open_cascade(conn, plan_uuid)
    if rec is None:
        raise CascadeError("plan has no open cascade")
    tip = get_ref(conn, plan_uuid, rec.name)
    change_set = diff(conn, plan_uuid, rec.base_revision_uuid, tip)
    nodes = load_steps(conn, plan_uuid)
    blast = sorted(
        artifact_path_of(nodes, s) for s in nodes.values() if s.status == "needs_review"
    )
    report, verdict = run_gate(conn, plan_uuid)
    return {
        "cascade_uuid": str(rec.uuid),
        "base_revision_uuid": str(rec.base_revision_uuid),
        "tip_revision_uuid": str(tip),
        "change_set": change_set,
        "needs_review": blast,
        "gate_green": report.green,
        "gate_report_json": render_json(report),
    }
