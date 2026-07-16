"""Pure derivation of a bug's fixing/fixed_source/propagating/verified status from its fix,
impact, and propagation records (C-009). Never called for a bug with no fix attempt at all, and
never invoked against a bug in a terminal status (closed/rejected/duplicate) or before terminal
guard clearance — callers (plan_manager.storage.bug_derived_status_store) are responsible for that
gating; this module is a pure function over already-extracted status lists.
"""
from __future__ import annotations

# BugImpact statuses that count as cleared for closure/derivation purposes.
CLEARED_IMPACT_STATUSES: frozenset[str] = frozenset({"unaffected", "verified", "skipped"})

# BugFixPropagation statuses that count as finished for closure/derivation purposes.
FINISHED_PROPAGATION_STATUSES: frozenset[str] = frozenset({"done", "verified", "skipped"})

def derive_bug_status(
    *,
    fix_statuses: list[str],
    fix_passed_flags: list[bool | None],
    impact_statuses: list[str],
    propagation_statuses: list[str],
) -> str | None:
    """Compute the derived bug status from its current fix/impact/propagation records (C-009).

    Args:
        fix_statuses: The status value of every BugFix record for the bug, in any order.
        fix_passed_flags: The passed value of every BugFix record for the bug, index-aligned
            with fix_statuses (None when the fix has not been verified yet).
        impact_statuses: The status value of every BugImpact record for the bug.
        propagation_statuses: The status value of every BugFixPropagation record across every
            BugFix of the bug.

    Returns:
        None when fix_statuses is empty (no fix attempt exists yet, so there is nothing to
        derive). Otherwise one of "fixing", "fixed_source", "propagating", or "verified":
          * "fixing" when no fix in fix_statuses has both status == "verified" and its
            index-aligned fix_passed_flags entry is True.
          * Otherwise (a verified, passed fix exists): "propagating" when propagation_statuses
            is non-empty and any entry is not in FINISHED_PROPAGATION_STATUSES; else
            "fixed_source" when impact_statuses is non-empty and any entry is not in
            CLEARED_IMPACT_STATUSES; else "verified".
    """
    if not fix_statuses:
        return None
    has_verified_passed_fix = any(
        status == "verified" and passed is True
        for status, passed in zip(fix_statuses, fix_passed_flags)
    )
    if not has_verified_passed_fix:
        return "fixing"
    if propagation_statuses and any(
        status not in FINISHED_PROPAGATION_STATUSES for status in propagation_statuses
    ):
        return "propagating"
    if impact_statuses and any(
        status not in CLEARED_IMPACT_STATUSES for status in impact_statuses
    ):
        return "fixed_source"
    return "verified"
