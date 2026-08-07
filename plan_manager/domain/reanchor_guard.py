"""Reanchor target guard: refuses moving a runtime record's primary anchor onto a frozen-truth target (C-012).

CR-7 G-007/T-001/A-004 (closes bug 5c0ddc16 by construction). Re-anchoring is
the one uniform operation the ownership model promises: an ordinary update of
owner, validated by the admission collaborator for acyclicity over the
affected ancestry, committed with the registry and relation-index changes in
one transaction, preserving the entity's ref, creation time and inbound
references.

guard_reanchor_target_not_frozen (below, UNCHANGED from the pre-A-004 shape)
is the existing frozen-truth refusal that todo_reanchor
(storage/todo_reanchor_store.py) and bug_reanchor (storage/
bug_reanchor_store.py) already route through, each still performing its own
discriminated update (PrimaryAnchor / BugSource respectively) -- that
behaviour is untouched by this step.

guard_owner_update (new, below) is the uniform capability this step adds: a
generic owner-update entry serving every runtime entity kind that shares the
legacy primary_anchor_type/anchor_* column family -- todo_item, wish_item,
calendar_entry, escalation (OWNER_UPDATE_TABLES; confirmed against the real
dataclasses in plan_manager.domain.todo/wish/calendar_entry/escalation, not
assumed). bug_report's distinct source_anchor_type/source_* family keeps its
own dedicated reanchor_bug_source route -- the two families use different
discriminator vocabularies (plan_manager.maintenance.anchor_cutover's own
FAMILY_SPECS documents the same split) and are not interchangeable, so a
"same generic entry" for bug_report would have to invent a second update
path rather than reuse primary_anchor.owner_form_to_columns's legacy-column
shape. The wish path (bug 5c0ddc16) uses guard_owner_update: a wish no
longer needs delete-and-recreate to move house. No new wish_reanchor command
surface is added here -- that is G-008's.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.primary_anchor import (
    InvalidAnchorError,
    anchor_from_columns,
    owner_form_to_columns,
    resolve_owner,
    validate_owner_change,
)
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
from plan_manager.storage.errors import NotFoundError
from plan_manager.storage.identity import resolve_entity_identity
from plan_manager.storage.reference_catalog import REFERENCE_CATALOG
from plan_manager.storage import relation_index_store


def guard_reanchor_target_not_frozen(
    conn: psycopg.Connection,
    anchor_type: str,
    plan_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID | None,
) -> None:
    """Refuse a re-anchor move whose candidate new target is a frozen plan or a frozen step.

    Only the anchor_type/source_type values "plan" and "step" are backed by
    frozen-truth tables (plan, step); every other value (project, file,
    revision, execution_attempt, review_result, bug, bug_fix, todo, none,
    command, runtime_service, unidentified) is not a frozen-truth table and
    is not checked by this guard.

    Parameters:
        conn: psycopg.Connection
            Open connection used to read the candidate target's status.
        anchor_type: str
            The candidate new anchor type or bug source type being moved to.
        plan_uuid: uuid.UUID | None
            The candidate plan UUID; read when anchor_type == "plan".
        step_uuid: uuid.UUID | None
            The candidate step UUID; read when anchor_type == "step".

    Raises:
        FrozenTruthMutationError: When anchor_type == "plan" and the plan
            row's status column equals "frozen", or when anchor_type ==
            "step" and the step row's status column equals "frozen". Does
            not raise when no row is found for the candidate identifier (a
            separate existence check is the caller's responsibility).
    """
    if anchor_type == "plan":
        row = conn.execute(
            "SELECT status FROM plan WHERE uuid = %s", (plan_uuid,)
        ).fetchone()
        if row is not None and row[0] == "frozen":
            raise FrozenTruthMutationError(
                f"cannot re-anchor onto frozen plan {plan_uuid}"
            )
    elif anchor_type == "step":
        row = conn.execute(
            "SELECT status FROM step WHERE uuid = %s", (step_uuid,)
        ).fetchone()
        if row is not None and row[0] == "frozen":
            raise FrozenTruthMutationError(
                f"cannot re-anchor onto frozen step {step_uuid}"
            )


# ---------------------------------------------------------------------------
# Owner-update surface (CR-7 G-007/T-001/A-004). Added ALONGSIDE the
# frozen-truth guard above -- see the module docstring's TRANSITION note.
# ---------------------------------------------------------------------------

OWNER_UPDATE_TABLES: frozenset[str] = frozenset(
    {"todo_item", "wish_item", "calendar_entry", "escalation"}
)
"""Tables guard_owner_update serves: the legacy primary_anchor_type/anchor_*
column family shared by these four dataclasses. bug_report's distinct
source_anchor_type/source_* family (BugSource) is a different vocabulary and
keeps its own reanchor_bug_source route -- see the module docstring."""

_ANCHOR_COLUMNS: tuple[str, ...] = (
    "primary_anchor_type",
    "anchor_project_id",
    "anchor_file_path",
    "anchor_plan_uuid",
    "anchor_revision_uuid",
    "anchor_step_uuid",
    "anchor_step_path",
    "anchor_ref_id",
)
"""The legacy anchor column set, identical across every OWNER_UPDATE_TABLES
member (confirmed against each dataclass's COLUMNS tuple) -- the exact
key/order primary_anchor.anchor_from_columns/anchor_to_columns expect."""


def _owner_ancestry_edges(conn: psycopg.Connection, start: uuid.UUID | None) -> list[tuple[str, str]]:
    """Walk the candidate new owner's OWN ownership chain upward, one hop per row.

    Returns child->owner edges (str pairs, the shape
    storage.admission.ensure_owner_acyclic consumes) for every hop taken.
    Ownership here is single-parent (a tree, not a general DAG): if the
    candidate new owner is already a descendant of the entity being moved,
    walking up from it necessarily passes back through that entity, so this
    ancestry-only walk supplies enough edges for ensure_owner_acyclic to
    detect the cycle the candidate edge would close -- this function does no
    detection itself, only edge collection.

    The walk stays inside OWNER_UPDATE_TABLES: reaching a plan, step,
    revision, an external project id (absent from the registry), or any
    entity kind outside this family (e.g. a bug_report, still on its own
    source_* family) ends the walk there -- those are roots for this
    collaborator's purposes during the transition, matching their own
    OWNER_GAP declarations elsewhere in the domain layer. A visited set
    guards against hanging on already-cyclic stored data, consistent with
    admission.py's own "reads stay cycle-tolerant" stance.
    """
    edges: list[tuple[str, str]] = []
    current = start
    visited: set[uuid.UUID] = set()
    while current is not None and current not in visited:
        visited.add(current)
        try:
            identity = resolve_entity_identity(conn, current)
        except NotFoundError:
            break
        table_name = identity["table_name"]
        if table_name not in OWNER_UPDATE_TABLES:
            break
        select_sql = "SELECT {} FROM {} WHERE uuid = %s".format(
            ", ".join(_ANCHOR_COLUMNS), table_name
        )
        row = conn.execute(select_sql, (current,)).fetchone()
        if row is None:
            break
        anchor = anchor_from_columns(dict(zip(_ANCHOR_COLUMNS, row)))
        parent = resolve_owner(conn, anchor)
        if parent is None:
            break
        edges.append((str(current), str(parent)))
        current = parent
    return edges


def guard_owner_update(
    conn: psycopg.Connection,
    entity_ref: uuid.UUID,
    new_owner: uuid.UUID | None,
    *,
    project_id: uuid.UUID | None = None,
    path: str | None = None,
    plan_uuid: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Move any OWNER_UPDATE_TABLES entity's owner to a new target, uniformly.

    The one generic re-anchor operation: entity_ref is resolved through the
    identity registry, the candidate new owner is validated for acyclicity
    over its own ancestry via primary_anchor.validate_owner_change ->
    storage.admission.ensure_owner_acyclic, a frozen-truth target is refused
    by guard_reanchor_target_not_frozen (reused exactly as todo_reanchor/
    bug_reanchor already document it), and the row's legacy anchor_* columns
    are overwritten in place -- an UPDATE only, never delete-recreate, so
    uuid, created_at and every inbound reference (relation_index rows and any
    other table's typed association) survive the move untouched. Every step
    runs in the caller's transaction; this function never commits or rolls
    back.

    Parameters:
        conn: psycopg.Connection
            Open connection; the caller owns the transaction.
        entity_ref: uuid.UUID
            The entity being moved. Must resolve, through the identity
            registry, to a table in OWNER_UPDATE_TABLES.
        new_owner: uuid.UUID | None
            The candidate new owner (owner-form: a bare entity uuid), or
            None to detach to a root (see primary_anchor.owner_form_to_anchor
            for the None/path root semantics).
        project_id: uuid.UUID | None
            Required alongside `path` for a root-with-descriptive-path
            (file) move; passed through to owner_form_to_columns unchanged.
        path: str | None
            Optional descriptive path for a None-owner (root) move.
        plan_uuid: uuid.UUID | None
            Required when new_owner resolves to a step (the legacy step
            anchor carries both plan_uuid and step_uuid).

    Returns:
        dict[str, Any]
            {"table_name", "entity_ref", **the eight written anchor columns}.

    Raises:
        NotFoundError: When entity_ref does not resolve through the identity
            registry.
        InvalidAnchorError: When entity_ref resolves to a table outside
            OWNER_UPDATE_TABLES, or when owner_form_to_columns's own shape/
            existence validation fails for new_owner.
        FrozenTruthMutationError: When the candidate new owner is a frozen
            plan or a frozen step (guard_reanchor_target_not_frozen).
        AdmissionCycleError: When the candidate owner change would close an
            ownership cycle (storage.admission.ensure_owner_acyclic).
    """
    identity = resolve_entity_identity(conn, entity_ref)
    table_name = identity["table_name"]
    if table_name not in OWNER_UPDATE_TABLES:
        raise InvalidAnchorError(
            f"guard_owner_update does not serve table {table_name!r} "
            f"(entity {entity_ref}); supported tables: {sorted(OWNER_UPDATE_TABLES)}"
        )

    new_columns = owner_form_to_columns(
        conn, new_owner, project_id=project_id, path=path, plan_uuid=plan_uuid
    )

    guard_reanchor_target_not_frozen(
        conn,
        new_columns["primary_anchor_type"],
        new_columns["anchor_plan_uuid"],
        new_columns["anchor_step_uuid"],
    )

    owner_edges = _owner_ancestry_edges(conn, new_owner)
    validate_owner_change(entity_ref, new_owner, owner_edges)

    now = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{column} = %s" for column in _ANCHOR_COLUMNS)
    conn.execute(
        f"UPDATE {table_name} SET {set_clause}, updated_at = %s WHERE uuid = %s",
        (*(new_columns[column] for column in _ANCHOR_COLUMNS), now, entity_ref),
    )

    for column in _ANCHOR_COLUMNS[1:]:  # skip the discriminator itself
        if (table_name, column) in REFERENCE_CATALOG:
            relation_index_store.record_reference(
                conn,
                source_ref=entity_ref,
                target_ref=new_columns[column],
                property_name=column,
            )

    return {"table_name": table_name, "entity_ref": entity_ref, **new_columns}
