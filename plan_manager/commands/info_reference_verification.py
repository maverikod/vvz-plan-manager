"""Verification-and-observability reference data for the info command (CR-3, C-001, C-011).

Describes, for an executing agent, the five CR-3 deliverables: the ops_status
observation command, the command_timing_stats performance aggregate, the
step_prompt_verify comparison command, the embedded-code gate check group,
and the audit_list read command. Consumed by plan_manager.commands.info_command
for both the capabilities section and the agent_reference section.
"""

from __future__ import annotations

from typing import Any


def verification_observability_capabilities() -> dict[str, Any]:
    """The capabilities-section descriptor for the CR-3 verification-and-observability group."""
    return {
        "summary": "Five read-only surfaces let an MCP-only operator verify produced artifacts, measure the running service, observe its deployed state and audit trail, and close a mechanical-gate blind spot, without direct database or shell access.",
        "deliverables": {
            "ops_status": {
                "command": "ops_status",
                "mutates": False,
                "paginated": False,
                "summary": "Returns the deployed version (image_tag, build_date), the health state (database and embedding service availability), and the applied schema_migration rows (filename, applied_at, newest first, with a count) in one response.",
            },
            "command_timing_stats": {
                "command": "command_timing_stats",
                "mutates": False,
                "paginated": True,
                "summary": "Aggregates the append-only command_metric store into per-command call counts and p50/p95/max latency percentiles, split into direct and queued call counts, filterable by command_name and a created_after/created_before time window.",
            },
            "step_prompt_verify": {
                "command": "step_prompt_verify",
                "mutates": False,
                "paginated": False,
                "summary": "Compares candidate artifact content (base64 bytes or a sha256 digest) against a frozen step's whole content, one field, or one fenced code block within a field, returning a match verdict, the canonical content hash, and on mismatch a unified diff and the first-divergence byte offset. Never mutates a step.",
            },
            "embedded_code_gate_check": {
                "command": None,
                "mutates": False,
                "paginated": False,
                "summary": "Not a standalone command: an additive mechanical-gate check group that parses fenced code blocks embedded in atomic-step prompts, reported as gate findings (the same shape as every other gate finding) through plan_validate. The pre-existing twenty checks across the gate's five original groups are unchanged.",
            },
            "audit_list": {
                "command": "audit_list",
                "mutates": False,
                "paginated": True,
                "summary": "Lists runtime audit log entries newest-first, filterable by actor, action, entity type, entity id, plan, and a created_after/created_before time window. The audit log has no write command of its own; every row is written only as the side effect of an existing mutating command.",
            },
        },
    }


def verification_observability_agent_reference() -> dict[str, Any]:
    """The agent_reference-section table for the CR-3 verification-and-observability group."""
    return {
        "purpose": "Closes the post-deploy verification gap where an operator previously needed direct shell, container, or database access: ops_status collapses that ritual into one call, command_timing_stats measures the running service, step_prompt_verify verifies a produced artifact byte-for-byte against its frozen source of truth, audit_list reads back the trail a mutating command leaves, and the embedded-code gate check catches malformed code blocks that previously passed a fully green gate.",
        "commands": {
            "ops_status": "Single read-only call returning version, health, and schema_migration rows together; takes no parameters.",
            "command_timing_stats": "Read-only aggregate over the command_metric store; optional command_name, created_after, created_before filters plus the uniform limit/offset pagination pair; returns items under the 'commands' key.",
            "step_prompt_verify": "Read-only comparison; required plan and step, optional candidate_base64 XOR candidate_sha256, optional field and block_index selectors; never mutates the compared step.",
            "audit_list": "Read-only listing over the runtime audit log; optional actor, action, entity_type, entity_id, plan, created_after, created_before filters plus the uniform limit/offset pagination pair; returns items under the 'items' key, newest first.",
        },
        "embedded_code_gate_check": "Reached only through plan_validate / cascade_commit's mechanical gate, not through a standalone command: a fenced code block in an atomic-step prompt is parsed by the language its fence info-string declares; an unparseable block yields an error finding naming the offending step, block, and parser error, in the same finding shape as every other gate check. The gate's original twenty checks across parse/identity/uniqueness/references/coverage are unchanged; the embedded-code group is additive.",
        "write_surfaces": "None of the five deliverables adds a write command: ops_status, command_timing_stats, step_prompt_verify, and audit_list are read-only, and the embedded-code gate check is reached only through the existing plan_validate/cascade_commit gate path.",
    }
