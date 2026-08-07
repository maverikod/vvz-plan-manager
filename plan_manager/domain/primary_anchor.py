"""Primary anchor domain: the single primary binding of a runtime entity to its subject (C-006).

CR-7 G-007/T-001/A-003 (the plan's deliberately-last breaking-contract step;
G-008 is its acceptance/governance record). The identity registry
(plan_manager.storage.identity) replaces the discriminator as the source of
truth for anchor ownership: an owner is a single UUID (or None for a root),
resolved the SAME way the G-007/T-001/A-002 cutover transport
(plan_manager.maintenance.anchor_cutover) resolves it, not by a second,
divergent mapping.

TRANSITION POSTURE (dual-write, add-alongside -- not replace-in-place). The
seventeen anchor-parameter commands and every store consuming this module
keep passing the pre-existing suite unmodified: validate_anchor and
anchor_to_columns/anchor_from_columns keep their public signatures and
behaviour for legacy callers untouched. The new owner-form surface below is
ADDED alongside them:

  * resolve_owner(conn, anchor) -> owner uuid | None, reading a legacy
    PrimaryAnchor.
  * owner_form_to_anchor / owner_form_to_columns, normalizing an owner-form
    input (a bare owner uuid + optional descriptive path) back INTO the
    legacy PrimaryAnchor / column-dict shape, so existing stores keep writing
    the legacy anchor_* columns during the transition. The legacy columns
    stay authoritative until the cutover drops them; the migration-0029
    owner/owner_uuid columns are populated by the G-007/T-001/A-002 transport
    (plan_manager.maintenance.anchor_cutover), NOT by this module -- this
    module only reads the registry to resolve/normalize, it never writes an
    owner column itself.
  * validate_owner_change, delegating ownership-cycle validation to
    plan_manager.storage.admission.ensure_owner_acyclic (the one admission
    collaborator for acyclicity, C-005/C-007) rather than a private copy.
  * owner_filter_predicate, an owner-column query helper added ALONGSIDE the
    legacy anchor-filter machinery the seventeen commands' stores already
    use (e.g. runtime_comment_store/todo_store's anchor_* WHERE-clause
    filters) -- not replacing it. It is opt-in: a caller only uses it once
    the row it is querying has been through the transport, so migrated data
    exists to filter on. The relation-index edge relation
    (plan_manager.storage.relation_index_store) that the FROZEN prompt's
    letter also names is a separate collaborator's concern (secondary,
    non-owner references), not this helper's.

The letter of the FROZEN A-003 prompt ("path anchors resolve to
root-with-descriptive-path", "the anchor-filtered query helpers this module
exposes are rewritten onto the owner column") would, taken literally, drop
or replace the legacy surface. That conflicts with the orchestrator's
compatibility gate (the pre-existing 2814-passed/6-skipped suite must stay
green pre-transport, before every row has an owner column populated). Where
the two conflict, THIS is the A-003 transition interpretation of record for
the G-008 governance note: add-alongside wins over rewrite-in-place; the
legacy helpers retire only at G-008's coordinated per-command metadata
release, not here.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

import psycopg

from plan_manager.domain.plan import refuse_if_completed
from plan_manager.domain.runtime_validation import (
    RuntimeValidationError, validate_uuid, validate_file_reference,
    validate_step_in_plan_revision, check_row_exists,
)
from plan_manager.storage.admission import ensure_owner_acyclic
from plan_manager.storage.errors import NotFoundError
from plan_manager.storage.identity import resolve_entity_identity

# Anchor validation (todo_create/comment/execution_attempt/review_result/
# escalation/bug anchors of anchor_type "plan" or "step") is the one
# plan-resolution path that does not go through
# plan_manager.commands.resolve.resolve_plan_guarded, since it takes a raw
# anchor_plan_uuid rather than a `plan` (name-or-uuid) command parameter.
# The completion-lock check itself is the single shared
# domain.plan.refuse_if_completed (bug c3950b83); this module has no
# private copy of that logic.
_check_plan_not_completed = refuse_if_completed


class InvalidAnchorError(RuntimeValidationError):
    """Raised when a candidate primary anchor fails validate_anchor's shape checks (missing
    required identifier fields for its anchor_type, or an unrecognized anchor_type); maps to
    INVALID_ANCHOR. Delegated checks (validate_uuid, validate_file_reference, check_row_exists,
    validate_step_in_plan_revision) keep raising the generic RuntimeValidationError."""


class PrimaryAnchorType(str, Enum):
    NONE = "none"
    PROJECT = "project"
    FILE = "file"
    PLAN = "plan"
    REVISION = "revision"
    STEP = "step"
    EXECUTION_ATTEMPT = "execution_attempt"
    REVIEW_RESULT = "review_result"
    BUG = "bug"
    BUG_FIX = "bug_fix"
    TODO = "todo"


ANCHOR_TYPES: frozenset[str] = frozenset(t.value for t in PrimaryAnchorType)


@dataclass(frozen=True)
class PrimaryAnchor:
    anchor_type: str
    project_id: uuid.UUID | None = None
    file_path: str | None = None
    plan_uuid: uuid.UUID | None = None
    revision_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None
    step_path: str | None = None
    ref_id: uuid.UUID | None = None


def validate_anchor(conn: psycopg.Connection, anchor: PrimaryAnchor) -> None:
    if anchor.anchor_type == "none":
        if (anchor.project_id is not None or
            anchor.file_path is not None or
            anchor.plan_uuid is not None or
            anchor.revision_uuid is not None or
            anchor.step_uuid is not None or
            anchor.step_path is not None or
            anchor.ref_id is not None):
            raise InvalidAnchorError("none anchor type must have all identifier fields as None")

    elif anchor.anchor_type == "project":
        if anchor.project_id is None:
            raise InvalidAnchorError("project anchor type requires project_id")
        validate_uuid(anchor.project_id)

    elif anchor.anchor_type == "file":
        if anchor.project_id is None or anchor.file_path is None:
            raise InvalidAnchorError("file anchor type requires project_id and file_path")
        validate_file_reference(anchor.project_id, anchor.file_path)

    elif anchor.anchor_type == "plan":
        if anchor.plan_uuid is None:
            raise InvalidAnchorError("plan anchor type requires plan_uuid")
        check_row_exists(conn, "plan", anchor.plan_uuid, frozenset({"plan"}))
        _check_plan_not_completed(conn, anchor.plan_uuid)

    elif anchor.anchor_type == "revision":
        if anchor.revision_uuid is None:
            raise InvalidAnchorError("revision anchor type requires revision_uuid")
        check_row_exists(conn, "revision", anchor.revision_uuid, frozenset({"revision"}))

    elif anchor.anchor_type == "step":
        if anchor.plan_uuid is None or anchor.step_uuid is None:
            raise InvalidAnchorError("step anchor type requires plan_uuid and step_uuid")
        validate_step_in_plan_revision(conn, anchor.plan_uuid, anchor.revision_uuid, anchor.step_uuid)
        _check_plan_not_completed(conn, anchor.plan_uuid)

    elif anchor.anchor_type in ("execution_attempt", "review_result", "bug", "bug_fix"):
        if anchor.ref_id is None:
            raise InvalidAnchorError(f"{anchor.anchor_type} anchor type requires ref_id")
        validate_uuid(anchor.ref_id)

    elif anchor.anchor_type == "todo":
        if anchor.ref_id is None:
            raise InvalidAnchorError("todo anchor type requires ref_id")
        check_row_exists(conn, "todo_item", anchor.ref_id, frozenset({"todo_item"}))

    else:
        raise InvalidAnchorError(f"unknown anchor type: {anchor.anchor_type}")


def anchor_to_columns(anchor: PrimaryAnchor) -> dict[str, Any]:
    return {
        "primary_anchor_type": anchor.anchor_type,
        "anchor_project_id": anchor.project_id,
        "anchor_file_path": anchor.file_path,
        "anchor_plan_uuid": anchor.plan_uuid,
        "anchor_revision_uuid": anchor.revision_uuid,
        "anchor_step_uuid": anchor.step_uuid,
        "anchor_step_path": anchor.step_path,
        "anchor_ref_id": anchor.ref_id,
    }


def anchor_from_columns(columns: dict[str, Any]) -> PrimaryAnchor:
    return PrimaryAnchor(
        anchor_type=columns["primary_anchor_type"],
        project_id=columns["anchor_project_id"],
        file_path=columns["anchor_file_path"],
        plan_uuid=columns["anchor_plan_uuid"],
        revision_uuid=columns["anchor_revision_uuid"],
        step_uuid=columns["anchor_step_uuid"],
        step_path=columns["anchor_step_path"],
        ref_id=columns["anchor_ref_id"],
    )


# ---------------------------------------------------------------------------
# Owner-form surface (CR-7 G-007/T-001/A-003). Added alongside the legacy
# surface above -- see the module docstring's TRANSITION POSTURE note.
# ---------------------------------------------------------------------------

# anchor_type -> the entity_identity.table_name a ref_id-bearing anchor must
# resolve to through the registry. This is the SAME discriminator -> owner
# mapping plan_manager.maintenance.anchor_cutover.SUFFIX_BY_DISCRIMINATOR
# encodes for the ``ref_id`` family (its five ref-suffixed kinds), kept here
# as a table-name lookup rather than a column-suffix lookup because
# resolve_owner confirms ownership THROUGH the registry, not by trusting the
# discriminator.
_REF_TABLE_BY_ANCHOR_TYPE: dict[str, str] = {
    PrimaryAnchorType.EXECUTION_ATTEMPT.value: "execution_attempt",
    PrimaryAnchorType.REVIEW_RESULT.value: "review_result",
    PrimaryAnchorType.BUG.value: "bug_report",
    PrimaryAnchorType.BUG_FIX.value: "bug_fix",
    PrimaryAnchorType.TODO.value: "todo_item",
}
_ANCHOR_TYPE_BY_REF_TABLE: dict[str, str] = {v: k for k, v in _REF_TABLE_BY_ANCHOR_TYPE.items()}


def resolve_owner(conn: psycopg.Connection, anchor: PrimaryAnchor) -> uuid.UUID | None:
    """Resolve a legacy-form PrimaryAnchor to its single owner UUID (None for a root).

    plan/step/revision map to their own uuid field directly (the discriminator
    already names the exact legacy column that holds the owner). The five
    ref_id-bearing kinds (execution_attempt, review_result, bug, bug_fix,
    todo) are resolved THROUGH the identity registry
    (plan_manager.storage.identity.resolve_entity_identity) instead: the
    registry, not the discriminator, is authoritative for which table a
    ref_id actually belongs to (per the module docstring's opening note), so
    a ref_id that resolves to a different table than the claimed anchor_type
    is rejected rather than trusted. project is an EXTERNAL id (never a local
    row) and is returned verbatim, with no registry lookup. file and none are
    roots and resolve to None -- see G-003's declared OWNER_GAP/root states.
    """
    if anchor.anchor_type in (PrimaryAnchorType.NONE.value, PrimaryAnchorType.FILE.value):
        return None
    if anchor.anchor_type == PrimaryAnchorType.PROJECT.value:
        return anchor.project_id
    if anchor.anchor_type == PrimaryAnchorType.PLAN.value:
        return anchor.plan_uuid
    if anchor.anchor_type == PrimaryAnchorType.STEP.value:
        return anchor.step_uuid
    if anchor.anchor_type == PrimaryAnchorType.REVISION.value:
        return anchor.revision_uuid
    expected_table = _REF_TABLE_BY_ANCHOR_TYPE.get(anchor.anchor_type)
    if expected_table is not None:
        identity = resolve_entity_identity(conn, anchor.ref_id)
        if identity["table_name"] != expected_table:
            raise InvalidAnchorError(
                f"{anchor.anchor_type} anchor ref_id {anchor.ref_id} resolves to table "
                f"{identity['table_name']!r} via the identity registry, not {expected_table!r}"
            )
        return identity["id"]
    raise InvalidAnchorError(f"unknown anchor type: {anchor.anchor_type}")


def owner_form_to_anchor(
    conn: psycopg.Connection,
    owner: uuid.UUID | None,
    *,
    project_id: uuid.UUID | None = None,
    path: str | None = None,
    plan_uuid: uuid.UUID | None = None,
) -> PrimaryAnchor:
    """Normalize an owner-form input (a bare owner uuid + optional descriptive
    path) into the legacy PrimaryAnchor shape, so existing stores keep
    writing the legacy anchor_* columns during the transition (dual-write
    posture -- see the module docstring).

    owner=None with no path normalizes to the "none" root. owner=None with a
    path normalizes to a "file" root-with-descriptive-path (per G-003's
    declared OWNER_GAP/root states); project_id must accompany the path, the
    same requirement validate_anchor enforces for a legacy file anchor.

    A non-None owner is resolved through the identity registry
    (resolve_entity_identity): the resolved table selects the legacy
    anchor_type and which legacy column the owner value lands in. A step
    owner additionally needs plan_uuid (the legacy step anchor carries both
    plan_uuid and step_uuid; the registry's step row does not itself carry
    the containing plan, so a caller normalizing a step-owner form must
    supply it). An owner uuid absent from the registry is treated as an
    external project id, stored verbatim -- project ids are never rows in
    entity_identity (anchor_cutover.py's SUFFIX_BY_DISCRIMINATOR: "project ->
    an EXTERNAL project id, not a local row").
    """
    if owner is None:
        if path is not None:
            if project_id is None:
                raise InvalidAnchorError(
                    "a root-with-path (file) anchor requires project_id alongside path"
                )
            return PrimaryAnchor(
                anchor_type=PrimaryAnchorType.FILE.value, project_id=project_id, file_path=path
            )
        return PrimaryAnchor(anchor_type=PrimaryAnchorType.NONE.value)

    try:
        identity = resolve_entity_identity(conn, owner)
    except NotFoundError:
        return PrimaryAnchor(anchor_type=PrimaryAnchorType.PROJECT.value, project_id=owner)

    table_name = identity["table_name"]
    if table_name == "plan":
        return PrimaryAnchor(anchor_type=PrimaryAnchorType.PLAN.value, plan_uuid=owner)
    if table_name == "revision":
        return PrimaryAnchor(anchor_type=PrimaryAnchorType.REVISION.value, revision_uuid=owner)
    if table_name == "step":
        if plan_uuid is None:
            raise InvalidAnchorError(
                "a step-owner anchor requires plan_uuid (the legacy step anchor carries both)"
            )
        return PrimaryAnchor(
            anchor_type=PrimaryAnchorType.STEP.value, plan_uuid=plan_uuid, step_uuid=owner
        )
    ref_anchor_type = _ANCHOR_TYPE_BY_REF_TABLE.get(table_name)
    if ref_anchor_type is not None:
        return PrimaryAnchor(anchor_type=ref_anchor_type, ref_id=owner)
    raise InvalidAnchorError(
        f"owner {owner} resolves to table {table_name!r}, which has no legacy anchor mapping"
    )


def owner_form_to_columns(
    conn: psycopg.Connection,
    owner: uuid.UUID | None,
    *,
    project_id: uuid.UUID | None = None,
    path: str | None = None,
    plan_uuid: uuid.UUID | None = None,
) -> dict[str, Any]:
    """owner_form_to_anchor, validated through validate_anchor and flattened to
    the legacy column dict (anchor_to_columns) a store writes unchanged."""
    anchor = owner_form_to_anchor(conn, owner, project_id=project_id, path=path, plan_uuid=plan_uuid)
    validate_anchor(conn, anchor)
    return anchor_to_columns(anchor)


def validate_owner_change(
    entity_ref: uuid.UUID | str,
    new_owner_ref: uuid.UUID | str | None,
    current_owner_edges: Iterable[tuple[str, str]] = (),
) -> None:
    """Validate an owner-form owner change for ownership acyclicity.

    Delegates to the one admission collaborator,
    plan_manager.storage.admission.ensure_owner_acyclic, rather than a
    private copy (letter (4) of the FROZEN A-003 prompt). The caller (a
    store making an owner write) supplies the owner edges of the affected
    neighbourhood; this function adds no graph-fetching logic of its own --
    see admission.py's own docstring for why the acyclicity walk is
    collapsed to one shared implementation.
    """
    ensure_owner_acyclic(current_owner_edges, entity_ref=entity_ref, new_owner_ref=new_owner_ref)


def owner_filter_predicate(owner_column: str, owner: uuid.UUID | None) -> tuple[str, tuple[Any, ...]]:
    """Build a SQL predicate filtering rows by a migration-0029 owner column.

    Added ALONGSIDE the legacy anchor-filter WHERE-clause construction the
    seventeen commands' stores already do against the anchor_* columns (not
    replacing it) -- a caller opts into this by naming the owner column of a
    table whose rows have been through the G-007/T-001/A-002 cutover
    transport (plan_manager.maintenance.anchor_cutover), since migrated data
    exists only after the transport runs. owner=None matches root rows
    (``{owner_column} IS NULL``); a UUID matches exactly
    (``{owner_column} = %s``). The returned params tuple is always ready to
    splice into a parameterized query's parameter list.
    """
    if owner is None:
        return f"{owner_column} IS NULL", ()
    return f"{owner_column} = %s", (owner,)
