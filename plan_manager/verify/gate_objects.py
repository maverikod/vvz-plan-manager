"""Object-inventory findings surfaced as mechanical-gate checks."""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of
from plan_manager.views.objects import object_findings, object_inventory


def _scoped_atomic_paths(tree: GateTree, steps: list[Step]) -> set[str]:
    return {
        artifact_path_of(tree.steps, step)
        for step in steps
        if step.level == 5
    }


def _object_gate_findings(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
    *,
    source_check: str,
    check_id: str,
) -> list[Finding]:
    scoped_paths = _scoped_atomic_paths(tree, steps)
    if not scoped_paths:
        return []
    inventory = object_inventory(conn, plan_uuid)
    findings = object_findings(inventory)
    result: list[Finding] = []
    for finding in findings:
        if finding["check"] != source_check:
            continue
        for artifact_path in finding["artifact_paths"]:
            if artifact_path not in scoped_paths:
                continue
            result.append(
                Finding(
                    check_id=check_id,
                    severity="error",
                    artifact_path=artifact_path,
                    message=finding["detail"],
                )
            )
    return result


def check_object_multiple_owner_keys(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
) -> list[Finding]:
    """Emit gate findings for duplicate object owner-key definitions."""
    return _object_gate_findings(
        conn,
        plan_uuid,
        tree,
        steps,
        source_check="multiple_owner_keys",
        check_id="coverage.object_multiple_owner_keys",
    )


def check_object_multiple_modules(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
) -> list[Finding]:
    """Emit gate findings for one object name drifting across modules."""
    return _object_gate_findings(
        conn,
        plan_uuid,
        tree,
        steps,
        source_check="multiple_modules",
        check_id="coverage.object_multiple_modules",
    )


def check_object_concepts_not_covered(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    tree: GateTree,
    steps: list[Step],
) -> list[Finding]:
    """Emit gate findings for object concept sets not covered by AS concepts."""
    return _object_gate_findings(
        conn,
        plan_uuid,
        tree,
        steps,
        source_check="concepts_not_covered",
        check_id="coverage.object_concepts_not_covered",
    )
