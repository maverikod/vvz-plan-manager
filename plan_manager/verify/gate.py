"""Mechanical gate orchestrator (C-012).

Fixed check-group order, byte-identical reports.
"""

import uuid

import psycopg

from plan_manager.verify.finding import Finding, Report, build_report, render_json
from plan_manager.verify.gate_code import check_embedded_code_parses
from plan_manager.verify.gate_context import (
    check_context_coverage_common_current,
    check_context_coverage_specific_subset,
)
from plan_manager.verify.gate_data import artifact_path_of, load_tree, scope_steps
from plan_manager.verify.gate_refs import (
    check_references_concepts,
    check_references_depends_on,
    check_references_relations,
    check_references_source_labels,
    check_uniqueness_concept_id,
    check_uniqueness_label,
    check_uniqueness_priority,
    check_uniqueness_step_id,
)
from plan_manager.verify.gate_structure import (
    check_identity_concept_id,
    check_identity_label,
    check_identity_slug,
    check_identity_step_id,
    check_parse_inputs_outputs,
    check_parse_required_fields,
    check_parse_sanity_counts,
    check_parse_target_file,
)
from plan_manager.verify.verdict import Verdict, current_head_revision
from plan_manager.views.branch import Branch
from plan_manager.views.coverage import (
    concept_coverage,
    gs_coverage,
    label_coverage,
    relation_coverage,
)

GROUP_ORDER = ["parse", "identity", "uniqueness", "references", "coverage", "embedded_code", "context_coverage"]

CHECK_IDS: dict[str, list[str]] = {
    "parse": [
        "parse.required_fields",
        "parse.inputs_outputs",
        "parse.target_file",
        "parse.sanity_counts",
    ],
    "identity": [
        "identity.step_id",
        "identity.slug",
        "identity.concept_id",
        "identity.label",
    ],
    "uniqueness": [
        "uniqueness.step_id",
        "uniqueness.concept_id",
        "uniqueness.label",
        "uniqueness.priority",
    ],
    "references": [
        "references.depends_on",
        "references.concepts",
        "references.relations",
        "references.source_labels",
    ],
    "coverage": [
        "coverage.concepts",
        "coverage.gs",
        "coverage.labels",
        "coverage.relations",
    ],
    "embedded_code": [
        "embedded_code.parses",
    ],
    "context_coverage": [
        "context_coverage.common_current",
        "context_coverage.specific_subset",
    ],
}


def check_coverage_concepts(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> list[Finding]:
    """Turn plan-level concept coverage gaps into findings."""
    report = concept_coverage(conn, plan_uuid)
    findings: list[Finding] = []
    for concept_id in report.missing:
        findings.append(
            Finding(
                check_id="coverage.concepts",
                severity="error",
                artifact_path="plan",
                message=f"concept {concept_id!r} missing",
            )
        )
    for concept_id in report.extra:
        findings.append(
            Finding(
                check_id="coverage.concepts",
                severity="error",
                artifact_path="plan",
                message=f"concept {concept_id!r} extra",
            )
        )
    return findings


def check_coverage_gs(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    gs_step_id: str | None = None,
) -> list[Finding]:
    """Turn per-GS child coverage gaps into findings."""
    reports = gs_coverage(conn, plan_uuid)
    findings: list[Finding] = []
    for step_id, report in sorted(reports.items()):
        if gs_step_id is not None and step_id != gs_step_id:
            continue
        for concept_id in report.missing:
            findings.append(
                Finding(
                    check_id="coverage.gs",
                    severity="error",
                    artifact_path=step_id,
                    message=f"concept {concept_id!r} missing",
                )
            )
    return findings


def check_coverage_labels(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> list[Finding]:
    """Turn plan-level label coverage gaps into findings."""
    report = label_coverage(conn, plan_uuid)
    findings: list[Finding] = []
    for label in report.missing:
        findings.append(
            Finding(
                check_id="coverage.labels",
                severity="error",
                artifact_path="plan",
                message=f"label {label!r} missing",
            )
        )
    for label in report.extra:
        findings.append(
            Finding(
                check_id="coverage.labels",
                severity="error",
                artifact_path="plan",
                message=f"label {label!r} extra",
            )
        )
    return findings


def check_coverage_relations(
    conn: psycopg.Connection, plan_uuid: uuid.UUID
) -> list[Finding]:
    """Turn plan-level relation coverage gaps into findings."""
    report = relation_coverage(conn, plan_uuid)
    findings: list[Finding] = []
    for relation in report.missing:
        findings.append(
            Finding(
                check_id="coverage.relations",
                severity="error",
                artifact_path="plan",
                message=f"relation {relation!r} missing",
            )
        )
    for relation in report.extra:
        findings.append(
            Finding(
                check_id="coverage.relations",
                severity="error",
                artifact_path="plan",
                message=f"relation {relation!r} extra",
            )
        )
    return findings


def run_gate(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    branch: Branch | None = None,
    fail_fast: bool = False,
) -> tuple[Report, Verdict]:
    """Run the mechanical gate (C-012) over ``plan_uuid``."""
    tree = load_tree(conn, plan_uuid)
    steps = scope_steps(tree, branch)
    run_check_ids: list[str] = []
    findings: list[Finding] = []
    for group in GROUP_ORDER:
        group_check_ids = CHECK_IDS[group]
        group_findings: list[Finding] = []
        if group == "parse":
            group_findings.extend(check_parse_required_fields(tree, steps))
            group_findings.extend(check_parse_inputs_outputs(tree, steps))
            group_findings.extend(check_parse_target_file(tree, steps))
            group_findings.extend(check_parse_sanity_counts(tree, steps, branch))
        elif group == "identity":
            group_findings.extend(check_identity_step_id(tree, steps))
            group_findings.extend(check_identity_slug(tree, steps))
            group_findings.extend(check_identity_concept_id(tree, steps))
            group_findings.extend(check_identity_label(tree, steps))
        elif group == "uniqueness":
            group_findings.extend(check_uniqueness_step_id(tree, steps))
            group_findings.extend(check_uniqueness_concept_id(tree, steps))
            group_findings.extend(check_uniqueness_label(tree, steps))
            group_findings.extend(check_uniqueness_priority(tree, steps))
        elif group == "references":
            group_findings.extend(check_references_depends_on(tree, steps))
            group_findings.extend(check_references_concepts(tree, steps))
            group_findings.extend(check_references_relations(tree, steps))
            group_findings.extend(check_references_source_labels(tree, steps))
        elif group == "coverage":
            if branch is None:
                group_findings.extend(check_coverage_concepts(conn, plan_uuid))
                group_findings.extend(check_coverage_gs(conn, plan_uuid, None))
                group_findings.extend(check_coverage_labels(conn, plan_uuid))
                group_findings.extend(check_coverage_relations(conn, plan_uuid))
            else:
                group_findings.extend(
                    check_coverage_gs(conn, plan_uuid, branch.gs.step_id)
                )
        elif group == "embedded_code":
            group_findings.extend(check_embedded_code_parses(tree, steps))
        elif group == "context_coverage":
            group_findings.extend(
                check_context_coverage_common_current(conn, plan_uuid, tree, steps)
            )
            group_findings.extend(
                check_context_coverage_specific_subset(conn, plan_uuid, tree, steps)
            )
        run_check_ids.extend(group_check_ids)
        findings.extend(group_findings)
        if fail_fast and group_findings:
            break
    findings_sorted = sorted(findings, key=lambda f: (f.artifact_path, f.check_id))
    report = build_report(run_check_ids, findings_sorted)
    scope_label = (
        "plan" if branch is None else artifact_path_of(tree.steps, branch.atomic)
    )
    verdict = Verdict(
        kind="gate",
        scope=scope_label,
        revision_uuid=current_head_revision(conn, plan_uuid),
        green=report.green,
        payload={"json": render_json(report)},
    )
    return report, verdict
