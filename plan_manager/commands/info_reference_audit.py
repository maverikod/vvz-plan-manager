"""Runtime audit log reference data for the info command (C-009, C-010, C-011).

Describes, for an executing agent, the read-only audit_list command over the
runtime audit log: its filter vocabulary, the closed ALLOWED_ACTIONS
vocabulary its action filter validates against, and the append-only,
read-only nature of the underlying audit read-model. Split into its own
module, alongside info_reference_delivery.py and the other sibling
info_reference_*.py modules, for file-size discipline (CR-1 C-014); consumed
by plan_manager.commands.info_command for the capabilities section.
"""

from __future__ import annotations

from typing import Any

from plan_manager.storage.runtime_audit_store import ALLOWED_ACTIONS


def runtime_audit_capabilities() -> dict[str, Any]:
    """The capabilities-section descriptor for the runtime audit log and audit_list."""
    return {
        "purpose": (
            "The runtime audit log (runtime_audit_log table) records every "
            "runtime mutation across the surface as an append-only trail: "
            "plan_uuid, entity_type, entity_id, action, changed_by, "
            "change_reason, changed_fields, and created_at. audit_list is the "
            "sole read command over this trail, closing the loop so an agent "
            "can run a mutating command and then read back its audit record "
            "without direct database access."
        ),
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "filters": {
            "actor": "Filters by the changed_by actor identifier.",
            "action": "Filters by the recorded action; must be one of allowed_actions or the command rejects it with INVALID_FILTER.",
            "entity_type": "Filters by the audited entity's type.",
            "entity_id": "Filters by the audited entity's identifier; must be a well-formed UUID string when supplied.",
            "plan": "Filters by the plan UUID the audit record is anchored to; must be a well-formed UUID string when supplied.",
            "created_after": "Filters to audit records created at or after this ISO-8601 timestamp.",
            "created_before": "Filters to audit records created at or before this ISO-8601 timestamp.",
        },
        "ordering": "Records are returned newest-first (descending by created_at), unlike the underlying store's append-only write order.",
        "commands": {
            "audit_list": {"mutates": False, "summary": "List runtime audit log entries filtered by actor, action, entity, plan, and time window, newest first, under uniform pagination."},
        },
        "write_surface": "None. The audit log has no create/update/delete command; every row is written only as the side effect of record_runtime_change calls made by the ~21 existing mutating commands that already audit their own changes.",
        "domain_errors": {
            "INVALID_FILTER": "A provided filter value failed validation for its declared field (wrong type, malformed UUID, or an action value outside allowed_actions).",
            "INVALID_PAGINATION": "A provided limit or offset value is not an integer, offset is negative, or limit is outside [1, 200].",
        },
    }
