"""Read-only preview of the plan's open cascade (C-016)."""

import uuid
from typing import Any

import psycopg

from plan_manager.cascade.record import CascadeError, get_open_cascade
from plan_manager.storage.version_store import get_ref
from plan_manager.storage.version_ops import diff
from plan_manager.storage.identity import resolve_entity_identities_batch
from plan_manager.views.dependency_graph import load_steps
from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import artifact_path_of
from plan_manager.verify.gate import run_gate
from plan_manager.verify.finding import render_json

# Deterministic category order for the unified detail-entries collection
# (todo 3c762bfe): added/removed/changed mirror diff()'s own vocabulary,
# needs_review is the blast radius, gate_finding is the flattened mechanical
# gate findings report. Every cascade_preview detail entry carries exactly
# one of these in its "category" field.
ENTRY_CATEGORY_ORDER: dict[str, int] = {
    "added": 0,
    "removed": 1,
    "changed": 2,
    "needs_review": 3,
    "gate_finding": 4,
}


def needs_review_steps(nodes: dict[uuid.UUID, Step]) -> list[Step]:
    """Return the needs_review blast-radius steps of `nodes`, sorted by artifact path.

    Args:
        nodes: Every step of one plan, as returned by load_steps().

    Returns:
        The subset of nodes.values() whose status equals "needs_review",
        sorted ascending by artifact_path_of(nodes, step).
    """
    return sorted(
        (s for s in nodes.values() if s.status == "needs_review"),
        key=lambda s: artifact_path_of(nodes, s),
    )


def _as_uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _classify_entity(
    entity_uuid: uuid.UUID,
    nodes: dict[uuid.UUID, Step],
    identities: dict[uuid.UUID, dict[str, Any]],
) -> tuple[str | None, str | None, str | None]:
    """Return (entity_type, step_path, step_status) for one change-set entity.

    A step entity classifies for free from the already-loaded `nodes` map
    (no query); any other entity type is looked up in the pre-resolved
    `identities` batch (see resolve_entity_identities_batch). An entity
    absent from both (e.g. a hard-deleted row) classifies as
    (None, None, None) rather than raising.
    """
    step = nodes.get(entity_uuid)
    if step is not None:
        return "step", artifact_path_of(nodes, step), step.status
    identity = identities.get(entity_uuid)
    if identity is not None:
        return identity.get("entity_type"), None, None
    return None, None, None


def _entry_sort_key(entry: dict[str, Any]) -> tuple:
    rank = ENTRY_CATEGORY_ORDER[entry["category"]]
    if entry["category"] == "gate_finding":
        return (rank, entry["check_id"], entry["artifact_path"], entry["message"])
    return (rank, entry.get("step_path") or "", entry["entity_uuid"])


def build_preview_entries(
    conn: psycopg.Connection,
    nodes: dict[uuid.UUID, Step],
    change_set: dict[str, Any],
    report: Any,
) -> list[dict[str, Any]]:
    """Build the unified, deterministically ordered cascade_preview detail entries.

    Flattens change_set's added/removed/changed, the needs_review blast
    radius, and the mechanical gate's flattened findings into ONE list of
    per-entry dicts, each tagged by a "category" key (one of
    ENTRY_CATEGORY_ORDER), so a single filter/pagination pass (see
    plan_manager.commands.cascade_preview_projection) covers every detail
    kind cascade_preview's contract exposes (todo 3c762bfe).

    Entity classification (entity_type/step_path/step_status) resolves
    steps for free from `nodes`; every other entity referenced by
    change_set is resolved in exactly one batched query via
    resolve_entity_identities_batch, never one query per entity.

    Args:
        conn: An open psycopg 3 database connection.
        nodes: Every step of the plan, as returned by load_steps().
        change_set: The diff() result (keys "added", "removed", "changed").
        report: The verify.finding.Report returned by run_gate().

    Returns:
        A new list of entry dicts, sorted by (category, secondary key).
    """
    added = change_set.get("added", [])
    removed = change_set.get("removed", [])
    changed = change_set.get("changed", [])

    change_entity_ids: set[uuid.UUID] = set()
    for value in added:
        change_entity_ids.add(_as_uuid(value))
    for value in removed:
        change_entity_ids.add(_as_uuid(value))
    for item in changed:
        change_entity_ids.add(_as_uuid(item["entity_uuid"]))

    unresolved = [eid for eid in change_entity_ids if eid not in nodes]
    identities = resolve_entity_identities_batch(conn, unresolved) if unresolved else {}

    entries: list[dict[str, Any]] = []
    for category, values in (("added", added), ("removed", removed)):
        for value in values:
            eid = _as_uuid(value)
            entity_type, step_path, step_status = _classify_entity(eid, nodes, identities)
            entries.append({
                "category": category,
                "entity_uuid": str(eid),
                "entity_type": entity_type,
                "step_path": step_path,
                "step_status": step_status,
            })
    for item in changed:
        eid = _as_uuid(item["entity_uuid"])
        entity_type, step_path, step_status = _classify_entity(eid, nodes, identities)
        entries.append({
            "category": "changed",
            "entity_uuid": str(eid),
            "entity_type": entity_type,
            "step_path": step_path,
            "step_status": step_status,
            "fields": list(item.get("fields", [])),
        })
    for step in needs_review_steps(nodes):
        entries.append({
            "category": "needs_review",
            "entity_uuid": str(step.uuid),
            "entity_type": "step",
            "step_path": artifact_path_of(nodes, step),
            "step_status": step.status,
        })
    for check in report.checks:
        for finding in check.findings:
            entries.append({
                "category": "gate_finding",
                "check_id": finding.check_id,
                "severity": finding.severity,
                "artifact_path": finding.artifact_path,
                "message": finding.message,
            })

    entries.sort(key=_entry_sort_key)
    return entries


def preview_cascade(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict:
    """Return the read-only preview of the plan's open cascade.

    Resolves the plan's open cascade record, computes the accumulated
    change set between the cascade's base revision and its current tip,
    classifies the needs_review blast radius by artifact path, runs the
    mechanical gate for a verdict and findings report, and builds the
    unified detail-entries collection (see build_preview_entries).
    Performs no writes: it records no revision, changes no status, and
    does not move the head.

    Args:
        conn: An open psycopg 3 database connection.
        plan_uuid: The UUID identity of the plan whose open cascade is
            previewed.

    Returns:
        A dict with exactly these keys:
        "cascade_uuid": str -- the open cascade record's UUID.
        "base_revision_uuid": str -- the revision UUID anchored at
            cascade opening.
        "tip_revision_uuid": str -- the current UUID resolved from the
            cascade's ref.
        "change_set": dict -- the diff() result between
            base_revision_uuid and tip_revision_uuid, with keys
            "added", "removed", "changed", each a list of node uuids
            (RAW, unbounded -- callers wanting a bounded response use the
            cascade_preview command's paginated "entries" projection
            instead of this key; kept here for internal/library reuse).
        "needs_review": list[str] -- artifact paths of steps whose
            status equals "needs_review", sorted ascending (RAW,
            unbounded; see the "entries" key for the paginated form).
        "gate_green": bool -- whether the mechanical gate run is green.
        "gate_report_json": str -- the machine-checkable JSON rendering
            of the gate findings report (RAW, unbounded).
        "entries": list[dict] -- the unified, deterministically ordered
            detail entries built by build_preview_entries(); the
            cascade_preview command paginates and filters THIS key by
            default rather than embedding the RAW keys above.

    Raises:
        CascadeError: if the plan has no open cascade.
    """
    rec = get_open_cascade(conn, plan_uuid)
    if rec is None:
        raise CascadeError("plan has no open cascade")
    tip = get_ref(conn, plan_uuid, rec.name)
    change_set = diff(conn, plan_uuid, rec.base_revision_uuid, tip)
    nodes = load_steps(conn, plan_uuid)
    blast = [artifact_path_of(nodes, s) for s in needs_review_steps(nodes)]
    report, verdict = run_gate(conn, plan_uuid)
    entries = build_preview_entries(conn, nodes, change_set, report)
    return {
        "cascade_uuid": str(rec.uuid),
        "base_revision_uuid": str(rec.base_revision_uuid),
        "tip_revision_uuid": str(tip),
        "change_set": change_set,
        "needs_review": blast,
        "gate_green": report.green,
        "gate_report_json": render_json(report),
        "entries": entries,
    }
