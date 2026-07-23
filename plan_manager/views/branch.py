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
from plan_manager.views.dependency_graph import load_steps


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


@dataclass
class BranchScope:
    """In-memory hierarchical branch-scope view (bug e197b94a): one resolved
    GS, optionally narrowed to one of its TS children, optionally narrowed
    further to one AS grandchild of that TS.

    Never persisted; held only in process memory for the duration of the
    consuming operation (the mechanical gate, C-012).

    Attributes:
        plan_uuid: Identity of the plan owning the scope.
        depth: Which selectors the caller supplied, in strict precedence
            order: "gs" (gs_step_id alone -- the whole GS subtree), "ts"
            (gs_step_id + ts_step_id -- that TS subtree), or "as"
            (gs_step_id + ts_step_id + as_step_id -- one atomic branch).
        gs: The resolved global (level 3) step. Always present.
        ts: The resolved tactical (level 4) step when depth is "ts" or
            "as"; None when depth is "gs".
        atomic: The resolved atomic (level 5) step when depth is "as";
            None otherwise.
        hrs_slice: The list of Paragraph rows bound to gs.fields
            ["source_labels"], in document order. Depends only on gs, so
            it is identical at every depth.
    """

    plan_uuid: uuid.UUID
    depth: str
    gs: Step
    ts: Step | None
    atomic: Step | None
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
        "fields, depends_on, concepts, project_id, status FROM step "
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
        project_id,
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
        project_id=project_id,
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
    nodes = load_steps(conn, plan_uuid)
    gs = next(
        (step for step in nodes.values() if step.level == 3 and step.step_id == gs_step_id),
        None,
    )
    if gs is None:
        raise BranchResolutionError(
            f"no step found at level 3 with step_id {gs_step_id!r}"
        )
    ts = next(
        (
            step
            for step in nodes.values()
            if step.level == 4
            and step.step_id == ts_step_id
            and step.parent_step_uuid == gs.uuid
        ),
        None,
    )
    if ts is None:
        raise BranchResolutionError(
            f"step {ts_step_id!r} does not belong to addressed parent {gs_step_id!r}"
        )
    atomic = next(
        (
            step
            for step in nodes.values()
            if step.level == 5
            and step.step_id == as_step_id
            and step.parent_step_uuid == ts.uuid
        ),
        None,
    )
    if atomic is None:
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


def resolve_branch_scope(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs_step_id: str,
    ts_step_id: str | None = None,
    as_step_id: str | None = None,
) -> BranchScope:
    """Resolve one hierarchical branch-scope address (bug e197b94a).

    Precedence: ``gs_step_id`` alone resolves the whole GS subtree
    (depth "gs"); ``gs_step_id`` + ``ts_step_id`` narrows to that TS
    subtree (depth "ts"); adding ``as_step_id`` narrows to one atomic
    branch (depth "as", equivalent in shape to ``resolve_branch``'s
    result). Unlike ``resolve_branch``, ``ts_step_id`` and
    ``as_step_id`` are optional here -- this function implements
    validation-over-existing-descendants: a GS with TS children but no
    AS descendants is a fully valid depth-"gs" or depth-"ts" scope.

    Parameters
    ----------
    conn: psycopg.Connection
        Open database connection. Only SELECT statements are issued,
        directly and via load_steps and list_paragraphs.
    plan_uuid: uuid.UUID
        Identity of the plan owning the scope.
    gs_step_id: str
        step_id of the global step (level 3), e.g. "G-002". Always
        required by this function's caller contract.
    ts_step_id: str | None
        step_id of the tactical step (level 4), e.g. "T-001", or None
        to stop at the GS subtree.
    as_step_id: str | None
        step_id of the atomic step (level 5), e.g. "A-001", or None to
        stop at the GS or TS subtree. Supplying this without
        ts_step_id is a skipped-level caller error; the command layer
        (plan_validate_command.validate_params) rejects that
        combination before this function is ever reached, but it is
        still defended here (raises BranchResolutionError) so this
        function is never silently wrong when called directly.

    Returns
    -------
    BranchScope
        plan_uuid, depth ("gs"/"ts"/"as"), the resolved gs Step (and ts
        / atomic Steps when selected), and hrs_slice: the list of
        Paragraph rows whose label (braces stripped) appears in the
        global step's fields["source_labels"] list, in document order
        as returned by list_paragraphs.

    Raises
    ------
    BranchResolutionError
        If gs cannot be found (names level 3 and gs_step_id); if
        ts_step_id is given but does not resolve as a level-4 child of
        gs (names ts_step_id as the child and gs_step_id as the
        addressed parent -- this message does not distinguish a
        nonexistent step_id from one that exists under a different
        parent, matching resolve_branch's existing convention); if
        as_step_id is given but does not resolve as a level-5 child of
        ts (same convention, naming as_step_id and ts_step_id); if
        as_step_id is given without ts_step_id (skipped level).
    """
    nodes = load_steps(conn, plan_uuid)
    gs = next(
        (step for step in nodes.values() if step.level == 3 and step.step_id == gs_step_id),
        None,
    )
    if gs is None:
        raise BranchResolutionError(
            f"no step found at level 3 with step_id {gs_step_id!r}"
        )
    ts: Step | None = None
    atomic: Step | None = None
    depth = "gs"
    if as_step_id and not ts_step_id:
        raise BranchResolutionError(
            f"as_step_id {as_step_id!r} given without ts_step_id "
            "(skipped level: as_step_id requires ts_step_id)"
        )
    if ts_step_id:
        ts = next(
            (
                step
                for step in nodes.values()
                if step.level == 4
                and step.step_id == ts_step_id
                and step.parent_step_uuid == gs.uuid
            ),
            None,
        )
        if ts is None:
            raise BranchResolutionError(
                f"step {ts_step_id!r} does not belong to addressed parent {gs_step_id!r}"
            )
        depth = "ts"
        if as_step_id:
            atomic = next(
                (
                    step
                    for step in nodes.values()
                    if step.level == 5
                    and step.step_id == as_step_id
                    and step.parent_step_uuid == ts.uuid
                ),
                None,
            )
            if atomic is None:
                raise BranchResolutionError(
                    f"step {as_step_id!r} does not belong to addressed parent {ts_step_id!r}"
                )
            depth = "as"
    source_labels = gs.fields.get("source_labels", [])
    bare = {label[1:-1] for label in source_labels}
    hrs_slice = [
        paragraph
        for paragraph in list_paragraphs(conn, plan_uuid)
        if paragraph.label is not None and paragraph.label in bare
    ]
    return BranchScope(
        plan_uuid=plan_uuid, depth=depth, gs=gs, ts=ts, atomic=atomic, hrs_slice=hrs_slice
    )
