"""Mechanical gate orchestrator (C-012).

Fixed check-group order, byte-identical reports.

``GATE_CHECK_SEMANTICS`` is defined in the sibling ``gate_semantics`` module
and re-exported here unchanged: EIG block F's four registered check_ids
pushed this file past the repository's hard ~400-line cap, and a pure data
table is the cheapest thing to lift out (same cap-driven split rationale as
``gate_execution_closure``/``gate_execution_existence``).
"""

import uuid
from typing import TYPE_CHECKING

import psycopg

from plan_manager.verify.finding import Finding, Report, build_report, render_json
from plan_manager.verify.gate_code import check_embedded_code_parses
from plan_manager.verify.gate_context import (
    check_context_coverage_common_current,
    check_context_coverage_specific_subset,
)
from plan_manager.verify.gate_data import artifact_path_of, load_tree, scope_steps
from plan_manager.verify.gate_execution import run_all as run_execution_integrity_checks
from plan_manager.verify.gate_objects import (
    check_object_concepts_not_covered,
    check_object_multiple_modules,
    check_object_multiple_owner_keys,
)
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
from plan_manager.verify.gate_semantics import (
    GATE_CHECK_SEMANTICS as GATE_CHECK_SEMANTICS,  # re-exported, see gate_semantics
)
from plan_manager.verify.gate_structure import (
    check_dependencies_same_file_order,
    check_identity_concept_id,
    check_identity_label,
    check_identity_slug,
    check_identity_step_id,
    check_parse_atomic_single_code_file,
    check_parse_inputs_outputs,
    check_parse_required_fields,
    check_parse_sanity_counts,
    check_parse_target_file,
)
from plan_manager.verify.verdict import Verdict, current_head_revision
from plan_manager.views.branch import BranchScope
from plan_manager.views.coverage import (
    concept_coverage,
    gs_coverage,
    label_coverage,
    relation_coverage,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps verify free of the CA transport
    from plan_manager.runtime.ca_files_probe import ExternalFilesProbe

GROUP_ORDER = [
    "parse", "identity", "uniqueness", "references", "coverage",
    "embedded_code", "context_coverage", "execution_integrity",
]

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
    "execution_integrity": [
        "execution_integrity.object_producer_before_consumer",
        "execution_integrity.execution_graph_acyclic",
        "execution_integrity.parallelization_safe",
        "execution_integrity.no_orphan_verification",
        "execution_integrity.test_coverage_present",
        "execution_integrity.release_artifact_closure",
        "execution_integrity.deployment_closure",
        "execution_integrity.no_unverified_production",
        # EIG block F (todo 763ae29e): CA-backed existence checks. All four
        # are silent unless run_gate is handed an external file probe --
        # see verify.gate_execution_existence's degraded-policy matrix.
        "execution_integrity.artifact_producer_exists",
        "execution_integrity.verification_target_resolvable",
        "execution_integrity.modify_file_context_available",
        "execution_integrity.external_project_unverified",
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
                message=f"concept {concept_id!r} not covered by any GS step",
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
                    message=f"concept {concept_id!r} not covered by any child (TS) step",
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
                message=f"label {label!r} not covered by any GS step",
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
                message=f"relation {relation!r} not covered by any GS step",
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
    branch: BranchScope | None = None,
    fail_fast: bool = False,
    *,
    external_files: "ExternalFilesProbe | None" = None,
    require_project_verification: bool = False,
) -> tuple[Report, Verdict]:
    """Run the mechanical gate (C-012) over ``plan_uuid``.

    When ``branch`` is a BranchScope (bug e197b94a), the checked scope
    is hierarchical: depth "gs" runs over the whole GS subtree, depth
    "ts" over one TS subtree, and depth "as" over exactly one atomic
    branch (the pre-fix behavior). ``coverage.gs`` is always evaluated
    for ``branch.gs.step_id`` regardless of depth: it is a GS-keyed
    concept-coverage check, unaffected by how far the caller narrowed
    the selectors. The verdict's scope label names the deepest selector
    the caller supplied (gs, gs/ts, or gs/ts/as).

    ``external_files`` (EIG block F, todo 763ae29e) is the live CA
    project-file inventory of the plan's primary analysis-server project,
    fetched by the CALLER (``runtime.ca_files_probe.list_project_files_probe``)
    so this function stays synchronous and free of I/O; it is threaded
    unchanged into the execution_integrity group.
    ``require_project_verification`` is the operator policy deciding whether
    an UNAVAILABLE probe is itself a finding. Both are keyword-only and
    default to the silent case: a caller that passes neither gets byte-
    identical reports to the pre-block-F gate.
    """
    tree = load_tree(conn, plan_uuid)
    steps = scope_steps(tree, branch)
    run_check_ids: list[str] = []
    findings: list[Finding] = []
    for group in GROUP_ORDER:
        group_check_ids = list(CHECK_IDS[group])
        group_findings: list[Finding] = []
        if group == "parse":
            group_findings.extend(check_parse_required_fields(tree, steps))
            group_findings.extend(check_parse_inputs_outputs(tree, steps))
            group_findings.extend(check_parse_target_file(tree, steps))
            group_findings.extend(check_parse_atomic_single_code_file(tree, steps))
            group_check_ids.append("parse.atomic_single_code_file")
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
            group_findings.extend(check_dependencies_same_file_order(tree, steps))
            group_check_ids.append("dependencies.same_file_order")
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
            group_findings.extend(
                check_object_multiple_owner_keys(conn, plan_uuid, tree, steps)
            )
            group_findings.extend(
                check_object_multiple_modules(conn, plan_uuid, tree, steps)
            )
            group_findings.extend(
                check_object_concepts_not_covered(conn, plan_uuid, tree, steps)
            )
            group_check_ids.extend(
                [
                    "coverage.object_multiple_owner_keys",
                    "coverage.object_multiple_modules",
                    "coverage.object_concepts_not_covered",
                ]
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
        elif group == "execution_integrity":
            group_findings.extend(
                run_execution_integrity_checks(
                    tree,
                    steps,
                    external_files=external_files,
                    require_project_verification=require_project_verification,
                )
            )
        run_check_ids.extend(group_check_ids)
        findings.extend(group_findings)
        if fail_fast and group_findings:
            break
    findings_sorted = sorted(findings, key=lambda f: (f.artifact_path, f.check_id))
    report = build_report(run_check_ids, findings_sorted)
    if branch is None:
        scope_label = "plan"
    elif branch.depth == "as":
        assert branch.atomic is not None
        scope_label = artifact_path_of(tree.steps, branch.atomic)
    elif branch.depth == "ts":
        assert branch.ts is not None
        scope_label = artifact_path_of(tree.steps, branch.ts)
    else:
        scope_label = artifact_path_of(tree.steps, branch.gs)
    verdict = Verdict(
        kind="gate",
        scope=scope_label,
        revision_uuid=current_head_revision(conn, plan_uuid),
        green=report.green,
        payload={"json": render_json(report)},
    )
    return report, verdict
