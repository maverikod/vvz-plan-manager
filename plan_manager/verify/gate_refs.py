"""Uniqueness and reference-resolution checks for the mechanical gate."""

from collections import defaultdict

from plan_manager.domain.relation import RELATION_TYPES
from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def check_uniqueness_step_id(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check step_id uniqueness within each parent scope."""
    findings: list[Finding] = []
    seen: dict[tuple[int, object, str], Step] = {}
    for step in steps:
        key = (step.level, step.parent_step_uuid, step.step_id)
        first = seen.get(key)
        if first is None:
            seen[key] = step
            continue
        findings.append(
            Finding(
                check_id="uniqueness.step_id",
                severity="error",
                artifact_path=_path(tree, step),
                message=f"duplicate step_id {step.step_id!r} in parent scope",
            )
        )
    return findings


def check_uniqueness_concept_id(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check concept_id uniqueness within the plan."""
    findings: list[Finding] = []
    seen: set[str] = set()
    for concept_id in tree.concept_ids:
        if concept_id in seen:
            findings.append(
                Finding(
                    check_id="uniqueness.concept_id",
                    severity="error",
                    artifact_path="concept",
                    message=f"duplicate concept_id {concept_id!r}",
                )
            )
        seen.add(concept_id)
    return findings


def check_uniqueness_label(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check paragraph label uniqueness within the plan."""
    findings: list[Finding] = []
    seen: set[str] = set()
    for label in tree.labels:
        if label in seen:
            findings.append(
                Finding(
                    check_id="uniqueness.label",
                    severity="error",
                    artifact_path="source_spec.md",
                    message=f"duplicate paragraph label {label!r}",
                )
            )
        seen.add(label)
    return findings


def check_uniqueness_priority(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check AS priority uniqueness within one target-file tactical scope."""
    findings: list[Finding] = []
    groups: dict[tuple[object, str], dict[object, Step]] = defaultdict(dict)
    for step in steps:
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        priority = step.fields.get("priority")
        key = (step.parent_step_uuid, target_file)
        first = groups[key].get(priority)
        if first is None:
            groups[key][priority] = step
            continue
        findings.append(
            Finding(
                check_id="uniqueness.priority",
                severity="error",
                artifact_path=_path(tree, step),
                message=(
                    f"duplicate priority {priority!r} for target_file "
                    f"{target_file!r}"
                ),
            )
        )
    return findings


def check_references_depends_on(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Resolve depends_on entries to sibling steps.

    ``depends_on`` is an ordering edge between siblings (same level, same
    parent), so its resolution universe is the full plan tree, not the
    scoped subset. Resolving against ``steps`` would make a branch-scoped
    run falsely report a sibling target as unresolved (the sibling is not
    in the branch triplet), yielding a scope-dependent verdict for one
    revision. Report only on ``steps`` but resolve against ``tree.steps``.
    """
    findings: list[Finding] = []
    scoped = {
        (step.level, step.parent_step_uuid, step.step_id)
        for step in tree.steps.values()
    }
    for step in steps:
        for dep_step_id in step.depends_on:
            if (step.level, step.parent_step_uuid, dep_step_id) not in scoped:
                findings.append(
                    Finding(
                        check_id="references.depends_on",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"depends_on target {dep_step_id!r} is unresolved",
                    )
                )
    return findings


def check_references_concepts(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Resolve every step concept reference into the MRS concept ids."""
    findings: list[Finding] = []
    concept_ids = set(tree.concept_ids)
    for step in steps:
        for concept_id in step.concepts:
            if concept_id not in concept_ids:
                findings.append(
                    Finding(
                        check_id="references.concepts",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"concept reference {concept_id!r} is unresolved",
                    )
                )
    return findings


def check_references_relations(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Resolve relation endpoints and relation types."""
    findings: list[Finding] = []
    concept_ids = set(tree.concept_ids)
    for from_concept, to_concept, relation_type in tree.relations:
        if from_concept not in concept_ids:
            findings.append(
                Finding(
                    check_id="references.relations",
                    severity="error",
                    artifact_path="relation",
                    message=f"from_concept {from_concept!r} is unresolved",
                )
            )
        if to_concept not in concept_ids:
            findings.append(
                Finding(
                    check_id="references.relations",
                    severity="error",
                    artifact_path="relation",
                    message=f"to_concept {to_concept!r} is unresolved",
                )
            )
        if relation_type not in RELATION_TYPES:
            findings.append(
                Finding(
                    check_id="references.relations",
                    severity="error",
                    artifact_path="relation",
                    message=f"relation type {relation_type!r} is unsupported",
                )
            )
    return findings


def check_references_source_labels(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Resolve braced source labels to stored binding paragraphs."""
    findings: list[Finding] = []
    labels = set(tree.labels)
    for step in steps:
        for source_label in step.fields.get("source_labels", []):
            bare = source_label[1:-1] if isinstance(source_label, str) else source_label
            if bare not in labels:
                findings.append(
                    Finding(
                        check_id="references.source_labels",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"source label {source_label!r} is unresolved",
                    )
                )
    return findings
