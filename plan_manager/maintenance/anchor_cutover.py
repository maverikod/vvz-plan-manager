"""CR-7 G-007/T-001/A-002: the non-destructive data move of the anchor collapse.

Migration 0029 (plan_manager_db/migrations/0029_owner_edge_schema.sql) is
Phase 1: additive DDL only. It adds a NULL-able ``owner``/``owner_uuid``
column to every table that still carries a discriminated anchor family (the
old ``anchor_*``/``source_*`` columns), but leaves those old columns and
every domain descriptor completely untouched -- no ``OWNER_COLUMN`` flips
from ``OWNER_GAP`` to the new column yet. That flip, and the DROP of the old
columns, are later, separate steps. This module is Phase 2: the transport
that reads each row's old discriminated family, resolves the single owner
UUID the discriminator names, and writes it into the new column -- without
touching the old columns and without requiring the domain descriptors to
change first.

THE MAPPING (discriminator -> owner suffix). One old column decides which of
the old anchor identifier columns holds the real owner:

    plan                                -> {prefix}_plan_uuid
    step                                -> {prefix}_step_uuid
    revision                            -> {prefix}_revision_uuid
    execution_attempt / review_result /
        bug / bug_fix / todo            -> {prefix}_ref_id
    escalation                          -> {prefix}_ref_id  (RuntimeComment's
                                            own 11th anchor kind, beyond the
                                            shared PrimaryAnchorType vocabulary
                                            -- see runtime_comment_store.
                                            add_comment: "escalation requires
                                            anchor_ref_id (checked against the
                                            escalation table)", the same
                                            ref_id column and semantics as the
                                            five kinds above)
    project                             -> {prefix}_project_id (an EXTERNAL
                                            project id, not a local row --
                                            still stored as the owner value
                                            verbatim; roots-with-path
                                            semantics per the G-003
                                            declarations, C-002)
    file                                -> NO owner; a root, with
                                            {prefix}_file_path kept as a
                                            descriptive attribute
    none                                -> NO owner (todo_item/wish_item/
                                            calendar_entry/escalation only --
                                            the shared PrimaryAnchorType
                                            vocabulary's empty state)
    command / runtime_service           -> NO owner (bug_report-only
                                            BugSourceType kinds; a root, with
                                            source_command/source_service
                                            kept as the descriptive attribute)
    unidentified                        -> NO owner (bug_report-only
                                            BugSourceType kind; no source
                                            information at all, analogous to
                                            "none")

``{prefix}`` is ``anchor`` for todo_item/wish_item/runtime_comment/
calendar_entry/escalation and ``source`` for bug_report. Discriminator
vocabularies differ per family and are NOT interchangeable -- confirmed
against the actual validators, not assumed:

  * todo_item, wish_item, calendar_entry, escalation all persist
    ``primary_anchor_type`` through plan_manager.domain.primary_anchor's
    shared ``PrimaryAnchor``/``validate_anchor`` (11 values: none, project,
    file, plan, revision, step, execution_attempt, review_result, bug,
    bug_fix, todo).
  * runtime_comment persists its own ``primary_anchor_type`` through its own
    ``CommentAnchorType`` (11 values, no "none", plus "escalation" in place
    of it -- see plan_manager/domain/runtime_comment.py).
  * bug_report persists ``source_anchor_type`` through
    plan_manager.domain.bug_source's own ``BugSourceType`` (9 values:
    project, file, plan, revision, step, command, runtime_service,
    execution_attempt, unidentified -- no todo/bug/bug_fix/review_result at
    all, and three kinds -- command, runtime_service, unidentified -- that
    have no equivalent in the shared vocabulary).

answer_envelope carries the ONE partial family (C-002's OWNER_GAP note on
plan_manager/domain/answer_envelope.py): anchor_plan_uuid/anchor_step_uuid/
attempt_uuid with NO discriminator column at all. Its owner precedence,
documented nowhere else, is fixed here: attempt_uuid wins if present, else
anchor_step_uuid, else anchor_plan_uuid, else no owner.

NON-OWNERSHIP TYPED ASSOCIATIONS. A row can carry more than one non-NULL
anchor identifier column at once (the clearest case: a "step" anchor also
carries the containing plan's anchor_plan_uuid). Whichever one the
discriminator did NOT select becomes a candidate relation-index edge
(plan_manager.storage.relation_index_store), written through
``record_reference`` with the column name as the property. A candidate is
only actually written when plan_manager.storage.reference_catalog.
REFERENCE_CATALOG already declares that exact (table, column) pair as a real
reference (respecting any ``const_filters``, e.g. runtime_comment/escalation
.anchor_ref_id is only catalogued for ``primary_anchor_type == "todo"``).
Where the catalog is silent, this module does NOT invent a new catalog
entry -- the candidate is recorded in the mapping report as an uncatalogued
decision and nothing is written for it. anchor_project_id/source_project_id
are never eligible for a relation-index edge (they are EXTERNAL_IDENTIFIER_
COLUMNS, not local rows) even when they are not the owner.

WRITE MECHANISM. The owner value is written through a small per-table
DataclassEntity "seat" (mirroring exchange/importer.py's own
_canonical_import_seat idiom) whose COLUMNS/OWNER_COLUMN/UPDATE_COLUMNS name
the new column -- so the write goes through entity.py's crud_update (one
parameterized ``UPDATE {table} SET {owner_column} = %s WHERE uuid = %s`` per
row), not hand-rolled SQL. Two reasons: it reuses the mechanism's already-
tested identity-safe UPDATE construction (parameter binding, quoted
identifiers, an immutable-id guard) instead of a second, parallel one; and
every write stays behind the entity.py mechanism boundary in spirit, even
though the G-004 no-out-of-mechanism-write scan (plan_manager/
pipeline_checks/registry.py) only patrols INSERT/DELETE and would not have
flagged a raw UPDATE either way. The seat is a local, throwaway class (never
registered, ENTITY_TYPE=None) built fresh per (entity class, owner column)
and cached for reuse within one call.

TRANSACTIONAL DISCIPLINE. This module never calls conn.commit()/
conn.rollback() -- exactly import_canonical_document's own documented
contract (exchange/importer.py): "operate in the caller's transaction...
any exception rolls back everything written". Every raise here (an
unrecognized discriminator value, a failed post-move verification) is meant
to propagate to a caller holding a real transaction, which rolls back
everything this module wrote for the call. dry_run=True performs zero
writes of either kind and returns the same report shape with every "written"
counter at zero, so mapping decisions can be inspected before anything
touches the database.

VERIFICATION. After the writes for one table, this module re-reads every row
of that table through the SAME seat (so the owner column is visible both
times) and canonicalizes both the pre- and post-move rows via
exchange/canonical_form.entity_row_to_canonical_record. Because the seat
declares OWNER_COLUMN=<the new column>, that function already separates
"owner" from "properties" for us. The comparison (see ``verify_move``)
requires every field except "owner" to be byte-for-byte identical, and
requires "owner" to equal exactly the value this module computed -- nothing
more, nothing less. Any other delta is a defect and raises before the old
columns could ever be considered for a DROP.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping

import psycopg

from plan_manager.domain.answer_envelope import AnswerEnvelope
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.wish import WishItem
from plan_manager.exchange import canonical_form as cf
from plan_manager.storage import relation_index_store
from plan_manager.storage.reference_catalog import (
    REFERENCE_CATALOG,
    REGISTRY_RESOLVED_OWNER_COLUMNS,
)


class AnchorCutoverError(RuntimeError):
    """Raised when a row's anchor family cannot be mapped, or a move fails verification."""


# --------------------------------------------------------------------------
# The discriminator -> owner-suffix mapping. This dict, and the per-family
# vocabulary sets below it, are the ONE place this mapping lives; per this
# module's own docstring and the frozen goal, it dies with the old schema.
# --------------------------------------------------------------------------

SUFFIX_BY_DISCRIMINATOR: dict[str, str | None] = {
    "plan": "plan_uuid",
    "step": "step_uuid",
    "revision": "revision_uuid",
    "execution_attempt": "ref_id",
    "review_result": "ref_id",
    "bug": "ref_id",
    "bug_fix": "ref_id",
    "todo": "ref_id",
    "escalation": "ref_id",  # runtime_comment's own 11th anchor kind
    "project": "project_id",
    "file": None,
    "none": None,
    "command": None,  # bug_report-only (BugSourceType)
    "runtime_service": None,  # bug_report-only (BugSourceType)
    "unidentified": None,  # bug_report-only (BugSourceType)
}

ROOT_LIKE_DISCRIMINATORS: frozenset[str] = frozenset({"file", "command", "runtime_service"})
"""Discriminator values with NO owner but a kept descriptive attribute (a root)."""

# Column suffixes eligible to become a secondary relation-index edge when
# they are NOT the owner-selected one. project_id is deliberately excluded:
# it is an EXTERNAL_IDENTIFIER_COLUMNS value, never a local row, in either role.
SECONDARY_CANDIDATE_SUFFIXES: tuple[str, ...] = ("plan_uuid", "step_uuid", "revision_uuid", "ref_id")

# Per-family discriminator vocabularies, confirmed against the real
# validators (plan_manager.domain.primary_anchor, plan_manager.domain.
# runtime_comment, plan_manager.domain.bug_source) rather than assumed.
PRIMARY_ANCHOR_FAMILY_VALUES: frozenset[str] = frozenset(
    {"none", "project", "file", "plan", "revision", "step", "execution_attempt", "review_result", "bug", "bug_fix", "todo"}
)
COMMENT_ANCHOR_FAMILY_VALUES: frozenset[str] = frozenset(
    {"plan", "revision", "step", "project", "file", "todo", "bug", "bug_fix", "execution_attempt", "review_result", "escalation"}
)
BUG_SOURCE_FAMILY_VALUES: frozenset[str] = frozenset(
    {"project", "file", "plan", "revision", "step", "command", "runtime_service", "execution_attempt", "unidentified"}
)

OWNER_COLUMN_BY_TABLE: dict[str, str] = dict(REGISTRY_RESOLVED_OWNER_COLUMNS)
"""table -> the migration-0029 owner column name (bug_report: owner_uuid)."""


@dataclass(frozen=True)
class FamilySpec:
    """One discriminated anchor family: which entity, which discriminator column,
    which old-column prefix, and which discriminator values are legitimate for it."""

    entity_cls: type
    discriminator_column: str
    prefix: str  # "anchor" or "source"
    valid_discriminators: frozenset[str]


FAMILY_SPECS: tuple[FamilySpec, ...] = (
    FamilySpec(TodoItem, "primary_anchor_type", "anchor", PRIMARY_ANCHOR_FAMILY_VALUES),
    FamilySpec(WishItem, "primary_anchor_type", "anchor", PRIMARY_ANCHOR_FAMILY_VALUES),
    FamilySpec(CalendarEntry, "primary_anchor_type", "anchor", PRIMARY_ANCHOR_FAMILY_VALUES),
    FamilySpec(Escalation, "primary_anchor_type", "anchor", PRIMARY_ANCHOR_FAMILY_VALUES),
    FamilySpec(RuntimeComment, "primary_anchor_type", "anchor", COMMENT_ANCHOR_FAMILY_VALUES),
    FamilySpec(BugReport, "source_anchor_type", "source", BUG_SOURCE_FAMILY_VALUES),
)

ANSWER_ENVELOPE_PRECEDENCE: tuple[str, ...] = ("attempt_uuid", "anchor_step_uuid", "anchor_plan_uuid")
"""answer_envelope's undiscriminated owner precedence, documented on this module only."""


# --------------------------------------------------------------------------
# Per-row mapping decisions -- pure, DB-free, directly unit-testable.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SecondaryRef:
    """One non-owner typed association found on a row."""

    column: str
    target: Any
    catalogued: bool


@dataclass(frozen=True)
class RowPlan:
    """The mapping decision for one row."""

    ref: uuid.UUID
    discriminator: str  # the raw discriminator value, or answer_envelope's synthetic label
    classification: str  # "owner_set" | "root" | "skipped"
    owner_column: str | None  # the OLD column the owner value was read from
    owner_value: Any
    secondary: tuple[SecondaryRef, ...]


def _is_catalogued_reference(table: str, column: str, row: Mapping[str, Any]) -> bool:
    """True when REFERENCE_CATALOG already declares (table, column) as a real
    reference for this row's own values (respecting any const_filters)."""
    entry = REFERENCE_CATALOG.get((table, column))
    if entry is None:
        return False
    return all(row.get(filter_column) == filter_value for filter_column, filter_value in entry.const_filters)


def _secondary_refs(table: str, prefix: str, row: Mapping[str, Any], owner_suffix: str | None) -> tuple[SecondaryRef, ...]:
    refs: list[SecondaryRef] = []
    for suffix in SECONDARY_CANDIDATE_SUFFIXES:
        if suffix == owner_suffix:
            continue
        column = f"{prefix}_{suffix}"
        if column not in row:
            continue
        value = row.get(column)
        if value is None:
            continue
        refs.append(SecondaryRef(column=column, target=value, catalogued=_is_catalogued_reference(table, column, row)))
    return tuple(refs)


def plan_row(spec: FamilySpec, row: Mapping[str, Any]) -> RowPlan:
    """Compute the mapping decision for one discriminated-family row.

    Raises:
        AnchorCutoverError: the row's discriminator value is not in this
            family's own confirmed vocabulary -- a data-integrity anomaly
            this module refuses to guess a mapping for.
    """
    discriminator = row[spec.discriminator_column]
    if discriminator not in spec.valid_discriminators:
        raise AnchorCutoverError(
            f"{spec.entity_cls.__name__} ref {row['uuid']}: unrecognized {spec.discriminator_column} "
            f"value {discriminator!r}; refusing to guess an owner mapping"
        )
    suffix = SUFFIX_BY_DISCRIMINATOR[discriminator]
    owner_column: str | None = None
    owner_value: Any = None
    classification = "skipped"
    if suffix is not None:
        column = f"{spec.prefix}_{suffix}"
        value = row.get(column)
        if value is not None:
            owner_column, owner_value, classification = column, value, "owner_set"
        # else: the discriminator names a target but the column is empty -- an
        # anomaly, not a crash; the row is reported as "skipped" like "none".
    elif discriminator in ROOT_LIKE_DISCRIMINATORS:
        classification = "root"

    secondary = _secondary_refs(spec.entity_cls.TABLE_NAME, spec.prefix, row, suffix if classification == "owner_set" else None)
    return RowPlan(
        ref=row["uuid"],
        discriminator=discriminator,
        classification=classification,
        owner_column=owner_column,
        owner_value=owner_value,
        secondary=secondary,
    )


def plan_answer_envelope_row(row: Mapping[str, Any]) -> RowPlan:
    """The undiscriminated answer_envelope precedence: attempt_uuid, else
    anchor_step_uuid, else anchor_plan_uuid, else no owner."""
    owner_column: str | None = None
    owner_value: Any = None
    for column in ANSWER_ENVELOPE_PRECEDENCE:
        value = row.get(column)
        if value is not None:
            owner_column, owner_value = column, value
            break
    classification = "owner_set" if owner_column is not None else "skipped"
    label = owner_column if owner_column is not None else "none"

    secondary = tuple(
        SecondaryRef(
            column=column,
            target=row.get(column),
            catalogued=_is_catalogued_reference(AnswerEnvelope.TABLE_NAME, column, row),
        )
        for column in ANSWER_ENVELOPE_PRECEDENCE
        if column != owner_column and row.get(column) is not None
    )
    return RowPlan(
        ref=row["uuid"],
        discriminator=label,
        classification=classification,
        owner_column=owner_column,
        owner_value=owner_value,
        secondary=secondary,
    )


# --------------------------------------------------------------------------
# Verification -- pure, directly unit-testable with crafted records.
# --------------------------------------------------------------------------


def verify_move(
    pre_records: Mapping[uuid.UUID, Mapping[str, Any]],
    post_records: Mapping[uuid.UUID, Mapping[str, Any]],
    expected_owner: Mapping[uuid.UUID, Any],
) -> list[str]:
    """Compare pre- and post-move canonical records for one table.

    Every field except "owner" must match exactly between the two documents;
    "owner" must equal ``expected_owner.get(ref)`` (canonicalized), or remain
    unset when the ref has no entry. Returns a list of problem descriptions
    (empty means the move is verified clean).
    """
    problems: list[str] = []
    if set(pre_records) != set(post_records):
        missing = set(pre_records) - set(post_records)
        extra = set(post_records) - set(pre_records)
        problems.append(f"row set changed during cutover: missing={sorted(map(str, missing))} extra={sorted(map(str, extra))}")
        return problems
    for ref, pre in pre_records.items():
        post = post_records[ref]
        for field in ("entity_kind", "markdel", "created_at", "updated_at", "properties"):
            if pre.get(field) != post.get(field):
                problems.append(f"{ref}: unexpected change in {field!r}: {pre.get(field)!r} -> {post.get(field)!r}")
        expected = expected_owner.get(ref)
        expected_canonical = cf._canonicalize_scalar(expected) if expected is not None else None
        if post.get("owner") != expected_canonical:
            problems.append(f"{ref}: owner mismatch: expected {expected_canonical!r}, got {post.get('owner')!r}")
    return problems


# --------------------------------------------------------------------------
# The write mechanism: a throwaway per-(entity, owner column) update seat.
# --------------------------------------------------------------------------

_OWNER_WRITE_SEATS: dict[tuple[type, str], type] = {}


def _owner_write_seat(entity_cls: type, owner_column: str) -> type:
    """A minimal DataclassEntity seat that can crud_list/crud_update the new
    owner column -- see this module's docstring, "WRITE MECHANISM", for why."""
    key = (entity_cls, owner_column)
    cached = _OWNER_WRITE_SEATS.get(key)
    if cached is not None:
        return cached
    namespace = dict(
        TABLE_NAME=entity_cls.TABLE_NAME,
        COLUMNS=tuple(entity_cls.COLUMNS) + (owner_column,),
        ID_COLUMN="uuid",
        ID_COLUMNS=(),
        INSERT_COLUMNS=(),
        UPDATE_COLUMNS=(owner_column,),
        SEARCH_COLUMNS=(),
        SOFT_DELETE_COLUMN=None,  # crud_list always returns every row, never hiding a marked one
        CREATED_AT_COLUMN=None,
        UPDATED_AT_COLUMN=None,
        ENTITY_TYPE=None,
        REGISTER_IDENTITY=False,
        ENGINE_MANAGED_TIMESTAMPS=False,
        OWNER_COLUMN=owner_column,
    )
    seat = type(f"_OwnerWriteSeat_{entity_cls.__name__}", (DataclassEntity,), namespace)
    _OWNER_WRITE_SEATS[key] = seat
    return seat


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------


def _write_secondary_refs(conn: psycopg.Connection, table: str, plans: list[RowPlan], *, dry_run: bool) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for plan in plans:
        for sref in plan.secondary:
            entry: dict[str, Any] = {
                "table": table,
                "ref": plan.ref,
                "column": sref.column,
                "target": sref.target,
                "catalogued": sref.catalogued,
                "written": False,
            }
            if sref.catalogued and not dry_run:
                field_ref = relation_index_store.record_reference(
                    conn, source_ref=plan.ref, target_ref=sref.target, property_name=sref.column,
                )
                entry["written"] = field_ref is not None
            report.append(entry)
    return report


def _discriminator_counts(plans: list[RowPlan]) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for plan in plans:
        counts[plan.discriminator][plan.classification] += 1
    return {
        discriminator: {"count": sum(by_classification.values()), "by_classification": dict(by_classification)}
        for discriminator, by_classification in counts.items()
    }


def _run_plans(
    conn: psycopg.Connection,
    entity_cls: type,
    owner_column: str,
    plans: list[RowPlan],
    pre_records: dict[uuid.UUID, dict[str, Any]],
    seat: type,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    table = entity_cls.TABLE_NAME
    owner_set_plans = [plan for plan in plans if plan.classification == "owner_set"]

    if not dry_run:
        for plan in owner_set_plans:
            seat.crud_update(conn, plan.ref, {owner_column: plan.owner_value}, returning=False)

    secondary_report = _write_secondary_refs(conn, table, plans, dry_run=dry_run)

    report: dict[str, Any] = {
        "total_rows": len(plans),
        "discriminator_counts": _discriminator_counts(plans),
        "owner_writes": {
            "planned": len(owner_set_plans),
            "written": 0 if dry_run else len(owner_set_plans),
        },
        "secondary_references": secondary_report,
        "relation_edges_written": 0 if dry_run else sum(1 for entry in secondary_report if entry["written"]),
    }

    if dry_run:
        report["verification"] = None
        return report

    post_rows = seat.crud_list(conn, include_marked=True)
    post_records = {row["uuid"]: cf.entity_row_to_canonical_record(seat, row) for row in post_rows}
    expected_owner = {plan.ref: plan.owner_value for plan in owner_set_plans}
    problems = verify_move(pre_records, post_records, expected_owner)
    if problems:
        raise AnchorCutoverError(f"{table}: cutover verification failed: " + "; ".join(problems))
    report["verification"] = {"status": "ok", "rows_checked": len(post_records)}
    return report


def _run_discriminated_family(conn: psycopg.Connection, spec: FamilySpec, *, dry_run: bool) -> dict[str, Any]:
    owner_column = OWNER_COLUMN_BY_TABLE[spec.entity_cls.TABLE_NAME]
    seat = _owner_write_seat(spec.entity_cls, owner_column)
    pre_rows = seat.crud_list(conn, include_marked=True)
    pre_records = {row["uuid"]: cf.entity_row_to_canonical_record(seat, row) for row in pre_rows}
    plans = [plan_row(spec, row) for row in pre_rows]
    return _run_plans(conn, spec.entity_cls, owner_column, plans, pre_records, seat, dry_run=dry_run)


def _run_answer_envelope(conn: psycopg.Connection, *, dry_run: bool) -> dict[str, Any]:
    owner_column = OWNER_COLUMN_BY_TABLE[AnswerEnvelope.TABLE_NAME]
    seat = _owner_write_seat(AnswerEnvelope, owner_column)
    pre_rows = seat.crud_list(conn, include_marked=True)
    pre_records = {row["uuid"]: cf.entity_row_to_canonical_record(seat, row) for row in pre_rows}
    plans = [plan_answer_envelope_row(row) for row in pre_rows]
    return _run_plans(conn, AnswerEnvelope, owner_column, plans, pre_records, seat, dry_run=dry_run)


def run_anchor_cutover(conn: psycopg.Connection, *, dry_run: bool = False) -> dict[str, Any]:
    """Move every anchor family's owner value into migration 0029's new column.

    Operates entirely inside the caller's own transaction (see this module's
    docstring, "TRANSACTIONAL DISCIPLINE"): never commits, never rolls back
    itself, and raises AnchorCutoverError on the first unrecognized
    discriminator value or failed post-move verification -- the caller's
    transaction is expected to roll back on that exception.

    dry_run=True performs zero writes (neither owner values nor relation-
    index edges) and skips verification (nothing moved); every other report
    field is identical in shape to a real run's.

    Returns:
        {"dry_run": bool, "tables": {table_name: {"total_rows", "discriminator_counts"
        ({value: {"count", "by_classification": {"owner_set"|"root"|"skipped": n}}}),
        "owner_writes" ({"planned", "written"}), "secondary_references" (list of
        {"table","ref","column","target","catalogued","written"}), "relation_edges_written",
        "verification" (None in dry-run, else {"status","rows_checked"})}}}
    """
    tables: dict[str, Any] = {}
    for spec in FAMILY_SPECS:
        tables[spec.entity_cls.TABLE_NAME] = _run_discriminated_family(conn, spec, dry_run=dry_run)
    tables[AnswerEnvelope.TABLE_NAME] = _run_answer_envelope(conn, dry_run=dry_run)
    return {"dry_run": dry_run, "tables": tables}
