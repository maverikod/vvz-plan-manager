"""Three-contour partition of one mechanical-gate report (EIG block G).

The gate has grown two very different kinds of check. The ORIGINAL groups
(parse, identity, uniqueness, references, coverage, embedded_code,
context_coverage) ask whether the plan is a well-formed, internally
consistent authoring artifact -- the STRUCTURAL contour. EIG blocks E1/E2/F
added ``execution_integrity``, which asks a different question entirely:
whether the plan, taken as an execution program, is ordered, closed, and
grounded in files that exist -- the EXECUTION contour. A third question,
"is the plan semantically complete", is answered by the scoring layer
(``scoring.index``), which is not a gate check at all -- the SEMANTIC
contour.

This module partitions ONE already-computed ``Report`` into the first two.
It runs no checks, touches no database, and never re-runs the gate: every
surface that reports contours does so from the single ``run_gate`` report it
already had, so the partition can never disagree with ``report.green``
(``structural.green and execution.green == report.green`` always holds).

The SEMANTIC contour has no findings of its own and is therefore composed by
each surface from its own scoring state -- see ``semantic_contour`` -- rather
than being derived here.
"""

from __future__ import annotations

from typing import Any

from plan_manager.verify.finding import Report

# Every execution_integrity check_id carries this prefix (see
# verify.gate.CHECK_IDS). The partition is prefix-driven rather than a
# literal check_id list so a new execution_integrity check joins the
# execution contour automatically, with no second place to update.
EXECUTION_CONTOUR_PREFIX = "execution_integrity."

CONTOUR_NAMES = ("structural", "execution", "semantic")

# The states the semantic contour may report at a surface.
#   scored        -- the scoring layer ran and produced an index.
#   deferred      -- scoring is available but was not computed here.
#   refused       -- scoring was refused because the gate is not green.
#   not_evaluated -- this surface never consults the scoring layer at all.
SEMANTIC_STATES = frozenset({"scored", "deferred", "refused", "not_evaluated"})


def empty_partition() -> dict[str, dict[str, Any]]:
    """Return the all-green structural/execution partition (zero findings)."""
    return {
        "structural": {"green": True, "findings_count": 0},
        "execution": {"green": True, "findings_count": 0},
    }


def structural_partition(findings_count: int) -> dict[str, dict[str, Any]]:
    """Return a partition carrying ``findings_count`` STRUCTURAL findings only.

    For the rare defect a caller counts itself, with no gate report behind it
    -- ``step_transition``'s freeze gate cannot even scope a run to a branch
    whose ancestry is broken, and records that as a structural finding.
    """
    return {
        "structural": {"green": findings_count == 0, "findings_count": findings_count},
        "execution": {"green": True, "findings_count": 0},
    }


def partition_contours(report: Report) -> dict[str, dict[str, Any]]:
    """Split ``report``'s findings into the structural and execution contours.

    Pure: derived from the report the caller already holds, never from a
    second gate run.

    Args:
        report: The ``Report`` returned by ``verify.gate.run_gate``.

    Returns:
        ``{"structural": {"green": bool, "findings_count": int},
        "execution": {"green": bool, "findings_count": int}}``. A check whose
        ``check_id`` starts with ``execution_integrity.`` counts toward the
        execution contour; every other check counts toward the structural
        one. A contour is green iff it has zero findings, so a report with
        no checks at all yields two green contours.
    """
    structural = 0
    execution = 0
    for check in report.checks:
        count = len(check.findings)
        if not count:
            continue
        if check.check_id.startswith(EXECUTION_CONTOUR_PREFIX):
            execution += count
        else:
            structural += count
    return {
        "structural": {"green": structural == 0, "findings_count": structural},
        "execution": {"green": execution == 0, "findings_count": execution},
    }


def merge_partitions(
    left: dict[str, dict[str, Any]], right: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Fold two partitions into one, summing counts per contour.

    Used by the only caller that runs the gate more than once for a single
    verdict (``commands.step_transition_command._run_transition_gate`` runs
    one scoped pass per atomic step), so the reported contours describe the
    whole transitioned scope rather than its last branch.
    """
    merged: dict[str, dict[str, Any]] = {}
    for name in ("structural", "execution"):
        count = left[name]["findings_count"] + right[name]["findings_count"]
        merged[name] = {"green": count == 0, "findings_count": count}
    return merged


def semantic_contour(state: str, reason: str | None = None) -> dict[str, Any]:
    """Build one surface's semantic-contour block.

    Args:
        state: One of ``SEMANTIC_STATES``.
        reason: Optional human-readable explanation. Always present in the
            returned dict (``None`` when not supplied) so the block's shape
            does not vary between surfaces.

    Returns:
        ``{"state": state, "reason": reason}``.

    Raises:
        ValueError: When ``state`` is not one of ``SEMANTIC_STATES``.
    """
    if state not in SEMANTIC_STATES:
        raise ValueError(f"unknown semantic contour state: {state!r}")
    return {"state": state, "reason": reason}


def contours_payload(
    partition: dict[str, dict[str, Any]] | None,
    semantic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the additive ``contours`` response key.

    Args:
        partition: A ``partition_contours`` result, or ``None`` for the
            all-green case (a surface that only ever reaches this point past
            a green gate, e.g. a computed score).
        semantic: A ``semantic_contour`` block, or ``None`` to omit the
            semantic contour entirely. Refusal payloads omit it: a refused
            call never consulted the scoring layer, and reporting a state for
            it would be an invention.

    Returns:
        A dict with "structural" and "execution", plus "semantic" when
        ``semantic`` is supplied.
    """
    payload: dict[str, Any] = dict(partition if partition is not None else empty_partition())
    if semantic is not None:
        payload["semantic"] = semantic
    return payload
