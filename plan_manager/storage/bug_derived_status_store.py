"""Orchestrates derived bug-status recomputation (C-009): fetches a bug's current fix, impact, and
propagation records, computes the derived status via plan_manager.domain.bug_derived_status, and
persists it through plan_manager.storage.bug_report_store.set_bug_status when it differs from the
bug's current status. Skips recomputation entirely for a bug that does not exist or whose current
status is terminal (closed/rejected/duplicate, per plan_manager.domain.bug_status_transitions.TERMINAL_STATUSES).
"""
from __future__ import annotations
import uuid

import psycopg

from plan_manager.domain.bug_derived_status import derive_bug_status
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.bug_status_transitions import TERMINAL_STATUSES
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_impact_store import list_bug_impacts
from plan_manager.storage.bug_report_store import get_bug, set_bug_status

def recompute_bug_status(conn: psycopg.Connection, bug_uuid: uuid.UUID, *, changed_by: str) -> BugReport | None:
    """Recompute and persist a bug's derived status from its fix/impact/propagation records (C-009).

    Args:
        conn: An open psycopg 3 connection.
        bug_uuid: UUID of the bug to recompute.
        changed_by: Actor identity recorded as the change actor when a status update is written.

    Returns:
        The bug's current BugReport after recomputation (unchanged when no derived status applies,
        when the bug's current status is terminal), or None when the bug does not exist.
    """
    bug = get_bug(conn, bug_uuid)
    if bug is None or bug.status in TERMINAL_STATUSES:
        return bug
    fixes = list_bug_fixes(conn, bug_uuid=bug_uuid)
    impacts = list_bug_impacts(conn, bug_uuid=bug_uuid)
    propagations = [
        propagation
        for fix in fixes
        for propagation in list_bug_fix_propagations(conn, bug_fix_uuid=fix.fix_uuid)
    ]
    derived = derive_bug_status(
        fix_statuses=[fix.status for fix in fixes],
        fix_passed_flags=[fix.passed for fix in fixes],
        impact_statuses=[impact.status for impact in impacts],
        propagation_statuses=[propagation.status for propagation in propagations],
    )
    if derived is not None and derived != bug.status:
        return set_bug_status(conn, bug_uuid, changed_by=changed_by, status=derived)
    return bug
