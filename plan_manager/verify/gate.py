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

# One-line semantic gloss per gate check, for embedding in command metadata/
# help (todo d8849951) so a caller can interpret gate_report_json findings
# without reading these check functions' docstrings. Every gloss states the
# comparison direction explicitly (which side is "required" and which side
# is "covering") to avoid the "missing" misreading that caused bugs 3de7a081
# and a8c43201: the gate always evaluates the plan's LIVE, current state
# (including any open cascade's working tip) -- never a stale or persisted
# snapshot. Scope is the coverage.* family plus the references.* family
# (the two families a caller is most likely to need explained to interpret
# a finding; the remaining checks' messages are self-explanatory).
GATE_CHECK_SEMANTICS: dict[str, str] = {
    "coverage.concepts": (
        "Every concept in the plan's concept table (MRS) must be declared "
        "on at least one GS step's own concepts; flags a concept not "
        "covered by any GS step, or a GS-declared concept with no matching "
        "row in the concept table ('extra')."
    ),
    "coverage.gs": (
        "Every concept a GS step declares on itself must be covered by the "
        "union of its own level-4 (TS) children's concepts; flags a "
        "GS-declared concept not covered by any child (TS) step's own "
        "decomposition -- NOT a statement that the concept is missing from "
        "the GS row itself (it is still there; it just is not yet covered "
        "by a TS child)."
    ),
    "coverage.labels": (
        "Every binding HRS paragraph label must be claimed by at least one "
        "GS step's source_labels; flags an HRS label not covered by any GS "
        "step, or a GS-claimed label with no matching binding HRS "
        "paragraph ('extra')."
    ),
    "coverage.relations": (
        "Every relation row in the plan's relation table (MRS) must be "
        "implemented by at least one GS step's own relations field; flags "
        "a relation not covered by any GS step, or a GS-declared relation "
        "with no matching row in the relation table ('extra')."
    ),
    "references.depends_on": (
        "Every step's depends_on entries must resolve to a sibling step_id "
        "(same level, same parent) that exists in the full plan tree."
    ),
    "references.concepts": (
        "Every step's own concepts entries must resolve to a concept_id "
        "defined in the plan's concept table (MRS)."
    ),
    "references.relations": (
        "Every relation row in the plan's relation table (MRS) must have "
        "both from_concept/to_concept resolve to a defined plan concept "
        "and a type that is one of the supported relation types."
    ),
    "references.source_labels": (
        "Every source_labels entry a step declares must resolve to a "
        "binding HRS paragraph label defined in the plan."
    ),
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
