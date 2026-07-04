"""Branch derived view (C-008): resolves one HRS-slice -> GS -> TS -> AS path
from the plan tree stored in the database into an in-memory, never-persisted
view. This module is read-only: it issues SELECT statements only against the
step and paragraph tables and never INSERTs, UPDATEs, or DELETEs.
"""

import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.step import Step
from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.paragraph_store import list_paragraphs


class BranchResolutionError(ValueError):
    """Raised when a branch address does not resolve.

    The exception message names the failing path element: for a missing
    step, the level and step_id that could not be found; for a step that
    does not belong to its addressed parent, the child's step_id and the
    addressed parent's step_id.
    """


@dataclass
class Branch:
    """In-memory branch view: one resolved HRS-slice -> GS -> TS -> AS path.

    Never persisted; held only in process memory for the duration of the
    consuming operation (verification or prompt assembly).
    """

    plan_uuid: uuid.UUID
    gs: Step
    ts: Step
    atomic: Step
    hrs_slice: list[Paragraph]


def _get_step_row(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, level: int, step_id: str
) -> Step:
    """Fetch one step row by plan, level, and step_id.

    Executes exactly:
        SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug,
               fields, depends_on, concepts, status
        FROM step
        WHERE plan_uuid = %s AND level = %s AND step_id = %s;

    Parameters
    ----------
    conn: psycopg.Connection
        Open database connection. Only SELECT is issued.
    plan_uuid: uuid.UUID
        Identity of the plan owning the step.
    level: int
        Step level to match (3 for GS, 4 for TS, 5 for AS).
    step_id: str
        Step identifier to match, e.g. "G-002", "T-001", "A-001".

    Returns
    -------
    Step
        Constructed from the fetched row. depends_on and concepts are the
        row's array columns converted with list(...); when a column
        value is NULL, an empty list [] is used instead.

    Raises
    ------
    BranchResolutionError
        If no row matches; the message names the level and step_id that
        could not be found.
    """
    row = conn.execute(
        "SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
        "fields, depends_on, concepts, status FROM step "
        "WHERE plan_uuid = %s AND level = %s AND step_id = %s;",
        (plan_uuid, level, step_id),
    ).fetchone()
    if row is None:
        raise BranchResolutionError(
            f"no step found at level {level} with step_id {step_id!r}"
        )
    (
        row_uuid,
        row_plan_uuid,
        parent_step_uuid,
        row_level,
        row_step_id,
        slug,
        fields,
        depends_on,
        concepts,
        status,
    ) = row
    return Step(
        uuid=row_uuid,
        plan_uuid=row_plan_uuid,
        parent_step_uuid=parent_step_uuid,
        level=row_level,
        step_id=row_step_id,
        slug=slug,
        fields=fields,
        depends_on=list(depends_on) if depends_on is not None else [],
        concepts=list(concepts) if concepts is not None else [],
        status=status,
    )


def resolve_branch(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs_step_id: str,
    ts_step_id: str,
    as_step_id: str,
) -> Branch:
    """Resolve one branch address to its in-memory Branch view.

    Fetches the global step (level 3), tactical step (level 4), and
    atomic step (level 5) identified by gs_step_id, ts_step_id, and
    as_step_id within the given plan, verifies parentage, and computes
    the HRS slice.

    Parameters
    ----------
    conn: psycopg.Connection
        Open database connection. Only SELECT statements are issued,
        directly and via _get_step_row and list_paragraphs.
    plan_uuid: uuid.UUID
        Identity of the plan owning the branch.
    gs_step_id: str
        step_id of the global step (level 3), e.g. "G-002".
    ts_step_id: str
        step_id of the tactical step (level 4), e.g. "T-001".
    as_step_id: str
        step_id of the atomic step (level 5), e.g. "A-001".

    Returns
    -------
    Branch
        plan_uuid, the fetched gs/ts/atomic Step rows, and hrs_slice: the
        list of Paragraph rows whose label (braces stripped) appears in
        the global step's fields["source_labels"] list, in document
        order as returned by list_paragraphs.

    Raises
    ------
    BranchResolutionError
        If gs, ts, or atomic cannot be found (raised inside
        _get_step_row, naming the missing level and step_id); if
        ts.parent_step_uuid does not equal gs.uuid (message names
        ts_step_id as the child and gs_step_id as the addressed parent);
        if atomic.parent_step_uuid does not equal ts.uuid (message names
        as_step_id as the child and ts_step_id as the addressed parent).
    """
    gs = _get_step_row(conn, plan_uuid, 3, gs_step_id)
    ts = _get_step_row(conn, plan_uuid, 4, ts_step_id)
    atomic = _get_step_row(conn, plan_uuid, 5, as_step_id)
    if ts.parent_step_uuid != gs.uuid:
        raise BranchResolutionError(
            f"step {ts_step_id!r} does not belong to addressed parent {gs_step_id!r}"
        )
    if atomic.parent_step_uuid != ts.uuid:
        raise BranchResolutionError(
            f"step {as_step_id!r} does not belong to addressed parent {ts_step_id!r}"
        )
    source_labels = gs.fields.get("source_labels", [])
    bare = {label[1:-1] for label in source_labels}
    hrs_slice = [
        paragraph
        for paragraph in list_paragraphs(conn, plan_uuid)
        if paragraph.label is not None and paragraph.label in bare
    ]
    return Branch(
        plan_uuid=plan_uuid, gs=gs, ts=ts, atomic=atomic, hrs_slice=hrs_slice
    )

