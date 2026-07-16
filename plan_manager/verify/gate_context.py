"""Context-coverage completeness net for the mechanical gate (C-004).

Extends the mechanical gate with a strictly additive check group that
audits the whole plan tree for context-coverage integrity, complementing
the write-time context-block admission guard (C-002, G-001). The guard
prevents contextless child creation as it happens; this module is the
retrospective net over the entire structure, catching trees that predate
the guard or were mutated around it. This module is read-only: it never
mutates the tree, any Step object, or any stored context_block row.

Two properties are asserted, one check_id per property:

- context_coverage.common_current: every global-step (level 3) or
  tactical-step (level 4) parent that has at least one child in the
  full plan tree holds a CURRENT common context_block (kind="common")
  for its children's level. A block compiled against a superseded plan
  revision, or against a cascade other than the plan's currently open
  one, counts as absent, mirroring the currency rule of C-003:
  staleness equals absence.

- context_coverage.specific_subset: every child step (level 4 or 5)
  whose parent has a current common block (per the check above) carries
  a concepts scope that is a subset of that current common block's
  scope_concepts. A child step's own `concepts` field is compared
  directly against the parent's live common scope, not against any
  cached context_block of kind "specific": trees authored before the
  admission guard existed never called context_specific at all, so an
  audit keyed on stored specific-delta rows would silently pass exactly
  the pre-guard trees this net exists to catch. A concept id present on
  the child but absent from the parent's current common scope produces
  one Finding per exceeding concept id. A child whose parent lacks a
  current common block is skipped: that gap is already reported by the
  other check, and comparing against an absent scope is meaningless.

Currency of a common context_block is determined against the plan's
live working state, read fresh on every call (never cached):

- If the plan has an open cascade, a common block is current iff its
  cascade_uuid equals that cascade's uuid AND its revision_uuid equals
  the revision the cascade's ref currently points to (looked up by the
  cascade's name). A block compiled earlier in the same open cascade,
  before a later edit advanced the cascade's ref, is stale.
- If the plan has no open cascade, a common block is current iff its
  cascade_uuid is NULL AND its revision_uuid equals the plan's
  head_revision_uuid.

When more than one common context_block is current for the same
(node_path, child_level) pair (e.g. two context_common calls with
different shared_concepts recorded under the same revision), the one
with the latest created_at is treated as the live one; ties (equal
created_at) keep whichever row the query returned first.

This module queries the database directly with `conn.execute(...)`,
mirroring the style of the sibling coverage-check module
(plan_manager/views/coverage.py), rather than reusing
plan_manager.cascade.record.get_open_cascade or
plan_manager.verify.verdict.current_head_revision (both of which use
the `conn.cursor()` context-manager idiom): a single query idiom keeps
this module trivially testable against a minimal fake connection that
implements only `.execute(...)`.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def _live_revision_and_cascade(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return (live_revision_uuid, live_cascade_uuid) for the plan's live state.

    When the plan has an open cascade, live_cascade_uuid is that
    cascade's uuid and live_revision_uuid is the revision its ref
    currently points to. Otherwise live_cascade_uuid is None and
    live_revision_uuid is the plan's head_revision_uuid. Either value
    may be None when the underlying row is not found (an open cascade
    with no ref row yet, or a plan with no head revision yet); callers
    treat None as "matches nothing", the conservative (report-missing)
    outcome.
    """
    cascade_row = conn.execute(
        "SELECT uuid, name FROM cascade WHERE plan_uuid = %s AND status = 'open'",
        (plan_uuid,),
    ).fetchone()
    if cascade_row is not None:
        cascade_uuid_value, cascade_name = cascade_row
        ref_row = conn.execute(
            "SELECT revision_uuid FROM ref WHERE plan_uuid = %s AND name = %s",
            (plan_uuid, cascade_name),
        ).fetchone()
        live_revision_uuid = ref_row[0] if ref_row is not None else None
        return live_revision_uuid, cascade_uuid_value
    head_row = conn.execute(
        "SELECT head_revision_uuid FROM plan WHERE uuid = %s",
        (plan_uuid,),
    ).fetchone()
    live_revision_uuid = head_row[0] if head_row is not None else None
    return live_revision_uuid, None


def _live_common_scope_by_key(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> dict[tuple[str, int], list[str]]:
    """Return the live common block's scope_concepts keyed by (node_path, child_level).

    Loads every kind="common" context_block row of the plan, filters to
    the rows CURRENT for the plan's live working state (see module
    docstring), and reduces same-key duplicates to the row with the
    latest created_at.
    """
    live_revision_uuid, live_cascade_uuid = _live_revision_and_cascade(conn, plan_uuid)

    rows = conn.execute(
        "SELECT node_path, child_level, revision_uuid, cascade_uuid, "
        "scope_concepts, created_at FROM context_block "
        "WHERE plan_uuid = %s AND kind = 'common'",
        (plan_uuid,),
    ).fetchall()

    best_created_at: dict[tuple[str, int], Any] = {}
    result: dict[tuple[str, int], list[str]] = {}
    for node_path, child_level, revision_uuid, cascade_uuid, scope_concepts, created_at in rows:
        if live_cascade_uuid is not None:
            is_current = cascade_uuid == live_cascade_uuid and revision_uuid == live_revision_uuid
        else:
            is_current = cascade_uuid is None and revision_uuid == live_revision_uuid
        if not is_current:
            continue
        key = (node_path, child_level)
        if key not in best_created_at or created_at > best_created_at[key]:
            best_created_at[key] = created_at
            result[key] = list(scope_concepts)
    return result


def check_context_coverage_common_current(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
) -> list[Finding]:
    """Find every scoped G/T parent-with-children lacking a current common block.

    Args:
        conn: Open database connection, used to read context_block,
            cascade, ref, and plan rows.
        plan_uuid: The plan whose live working state defines currency.
        tree: The loaded read-only plan tree, used to determine each
            candidate parent's children (across the full tree) and to
            resolve artifact paths.
        steps: The steps in the current gate run's scope. Only steps of
            level 3 or 4 present in this list are checked as candidate
            parents; a parent's children are looked up in the full
            tree, not restricted to this list.

    Returns:
        A list of Finding objects, one per scoped G/T parent that has
        at least one child in the full tree and has no current common
        context_block for its children's level, attributed to the
        parent's artifact path. Every Finding has check_id
        "context_coverage.common_current" and severity "error".
    """
    live_scope_by_key = _live_common_scope_by_key(conn, plan_uuid)
    has_child: set[uuid.UUID] = set()
    for step in tree.steps.values():
        if step.parent_step_uuid is not None:
            has_child.add(step.parent_step_uuid)

    findings: list[Finding] = []
    for step in steps:
        if step.level not in (3, 4):
            continue
        if step.uuid not in has_child:
            continue
        child_level = step.level + 1
        key = (_path(tree, step), child_level)
        if key not in live_scope_by_key:
            findings.append(
                Finding(
                    check_id="context_coverage.common_current",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message=(
                        f"no current common context block for child_level {child_level}"
                    ),
                )
            )
    return findings


def check_context_coverage_specific_subset(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
) -> list[Finding]:
    """Find every scoped child step whose concepts exceed its parent's live common scope.

    Args:
        conn: Open database connection, used to read context_block,
            cascade, ref, and plan rows.
        plan_uuid: The plan whose live working state defines currency.
        tree: The loaded read-only plan tree, used to resolve each
            child's parent and artifact path.
        steps: The steps in the current gate run's scope. Only steps of
            level 4 or 5 present in this list are checked as candidate
            children.

    Returns:
        A list of Finding objects, one per (child, exceeding concept
        id) pair, attributed to the child's artifact path. A child
        whose parent is not found in the tree, or whose parent has no
        current common block, produces no Finding here. Every Finding
        has check_id "context_coverage.specific_subset" and severity
        "error".
    """
    live_scope_by_key = _live_common_scope_by_key(conn, plan_uuid)

    findings: list[Finding] = []
    for step in steps:
        if step.level not in (4, 5):
            continue
        parent = tree.steps.get(step.parent_step_uuid)
        if parent is None:
            continue
        key = (_path(tree, parent), step.level)
        common_scope = live_scope_by_key.get(key)
        if common_scope is None:
            continue
        exceeding = sorted(set(step.concepts) - set(common_scope))
        for concept_id in exceeding:
            findings.append(
                Finding(
                    check_id="context_coverage.specific_subset",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message=(
                        f"concept {concept_id!r} exceeds parent common scope "
                        f"{common_scope!r}"
                    ),
                )
            )
    return findings
