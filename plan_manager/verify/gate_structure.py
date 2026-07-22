"""Parse and identity checks for the mechanical gate (C-012)."""

import re
from pathlib import PurePosixPath

from plan_manager.domain.concept import CONCEPT_ID_PATTERN
from plan_manager.domain.step import SLUG_PATTERN, STEP_ID_PATTERNS, Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.same_file_order import same_file_order_conflicts


LABEL_PATTERN = re.compile(r"^[0-9a-z]{4}$")

REQUIRED_FIELDS_BY_LEVEL: dict[int, tuple[str, ...]] = {
    3: ("name", "description", "relations", "source_labels"),
    4: ("name", "description", "inputs", "outputs"),
    5: ("name", "target_file", "operation", "priority", "prompt", "verification"),
}


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def check_parse_required_fields(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check level-specific field presence for every scoped step."""
    findings: list[Finding] = []
    for step in steps:
        required = REQUIRED_FIELDS_BY_LEVEL.get(step.level, ())
        for field_name in required:
            value = step.fields.get(field_name)
            if value in (None, "", [], {}):
                findings.append(
                    Finding(
                        check_id="parse.required_fields",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"required field {field_name!r} is missing or empty",
                    )
                )
    return findings


def check_parse_inputs_outputs(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check structured tactical inputs and outputs."""
    findings: list[Finding] = []
    for step in steps:
        if step.level != 4:
            continue
        for field_name in ("inputs", "outputs"):
            value = step.fields.get(field_name)
            if not isinstance(value, list):
                findings.append(
                    Finding(
                        check_id="parse.inputs_outputs",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"{field_name} must be a list",
                    )
                )
                continue
            for index, item in enumerate(value):
                if not isinstance(item, dict):
                    findings.append(
                        Finding(
                            check_id="parse.inputs_outputs",
                            severity="error",
                            artifact_path=_path(tree, step),
                            message=f"{field_name}[{index}] must be an object",
                        )
                    )
                    continue
                for key in ("name", "type", "description"):
                    if not isinstance(item.get(key), str) or not item[key].strip():
                        findings.append(
                            Finding(
                                check_id="parse.inputs_outputs",
                                severity="error",
                                artifact_path=_path(tree, step),
                                message=(
                                    f"{field_name}[{index}].{key} must be "
                                    "a non-empty string (expected item shape "
                                    "{name, type, description}; type must be "
                                    'one of "input" or "output")'
                                ),
                            )
                        )
    return findings


def check_parse_target_file(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check every atomic step has one non-empty project-relative target file."""
    findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if not isinstance(target_file, str) or not target_file.strip():
            findings.append(
                Finding(
                    check_id="parse.target_file",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message="target_file must be a non-empty string",
                )
            )
            continue
        if target_file.startswith("/") or ".." in target_file.split("/"):
            findings.append(
                Finding(
                    check_id="parse.target_file",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message="target_file must be project-relative",
                )
            )
    return findings



_CODE_PATH_RE = re.compile(
    r"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|pyi|js|jsx|ts|tsx|java|kt|go|rs|c|cc|cpp|h|hpp|cs|php|rb|swift|scala|sh|sql)(?![\w-])"
)
_WRITE_INTENT_RE = re.compile(
    r"\b(?:create|write|modify|edit|update|replace|delete|remove|rename|move|patch|append|insert|создать|создай|записать|изменить|изменяй|редактировать|редактируй|удалить|удаляй|переименовать|переместить|добавить)\b",
    re.IGNORECASE,
)


def _normal_path(value: str) -> str:
    return PurePosixPath(value.strip("`'\".,:;()[]{}<> ")).as_posix()


def _additional_write_targets(step: Step, target_file: str) -> dict[str, list[str]]:
    """Return explicit code paths mentioned on write-intent lines, by field."""
    normalized_target = _normal_path(target_file)
    result: dict[str, list[str]] = {}
    for field_name in ("prompt", "verification", "operation"):
        value = step.fields.get(field_name)
        if not isinstance(value, str):
            continue
        matches: set[str] = set()
        segments = re.split(r"(?<=[.!?;])\s+|\n+", value)
        for segment in segments:
            if not _WRITE_INTENT_RE.search(segment):
                continue
            for raw_path in _CODE_PATH_RE.findall(segment):
                path = _normal_path(raw_path)
                if path != normalized_target:
                    matches.add(path)
        if matches:
            result[field_name] = sorted(matches)
    return result


def check_parse_atomic_single_code_file(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Reject an AS that explicitly instructs writes to a second code file."""
    findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if not isinstance(target_file, str) or not target_file.strip():
            continue
        additional = _additional_write_targets(step, target_file)
        if additional:
            paths = sorted({path for values in additional.values() for path in values})
            findings.append(Finding(
                check_id="parse.atomic_single_code_file",
                severity="error",
                artifact_path=_path(tree, step),
                message=(
                    "AS_MULTIPLE_CODE_FILES: target_file="
                    f"{target_file!r}; additional_write_targets={paths!r}; "
                    f"source_fields={sorted(additional)!r}"
                ),
            ))
    return findings


def check_dependencies_same_file_order(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Reject same-file AS pairs whose cross-branch order is ambiguous."""
    scoped_ids = {step.uuid for step in steps if step.level == 5}
    edges = build_edges(tree.steps, strict_same_file_order=False)
    findings: list[Finding] = []
    for first_uuid, second_uuid, target_file in same_file_order_conflicts(tree.steps, edges):
        if first_uuid not in scoped_ids and second_uuid not in scoped_ids:
            continue
        first = tree.steps[first_uuid]
        second = tree.steps[second_uuid]
        writer_paths = sorted([_path(tree, first), _path(tree, second)])
        findings.append(Finding(
            check_id="dependencies.same_file_order",
            severity="error",
            artifact_path=writer_paths[0],
            message=(
                "AS_SAME_FILE_ORDER_AMBIGUOUS: target_file="
                f"{target_file!r}; writers={writer_paths!r}; "
                "add an explicit dependency between their TS/GS branches"
            ),
        ))
    return findings

def check_parse_sanity_counts(
    tree: GateTree, steps: list[Step], branch: Branch | None
) -> list[Finding]:
    """Make parser regressions fail loudly through expected non-zero counts."""
    findings: list[Finding] = []
    if branch is None:
        expected = ("steps", "concepts", "paragraphs")
        for key in expected:
            if tree.counts.get(key, 0) <= 0:
                findings.append(
                    Finding(
                        check_id="parse.sanity_counts",
                        severity="error",
                        artifact_path="plan",
                        message=f"{key} count must be non-zero",
                    )
                )
    elif not branch.hrs_slice:
        findings.append(
            Finding(
                check_id="parse.sanity_counts",
                severity="error",
                artifact_path=_path(tree, branch.gs),
                message="branch hrs_slice is empty",
            )
        )
    return findings


def check_identity_step_id(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check step identifier pattern and zero-padding conformance."""
    findings: list[Finding] = []
    for step in steps:
        pattern = STEP_ID_PATTERNS.get(step.level)
        if pattern is None or not pattern.match(step.step_id):
            findings.append(
                Finding(
                    check_id="identity.step_id",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message=(
                        f"step_id {step.step_id!r} does not match level "
                        f"{step.level}"
                    ),
                )
            )
    return findings


def check_identity_slug(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check slug conformance for every scoped step."""
    findings: list[Finding] = []
    for step in steps:
        if not isinstance(step.slug, str) or not SLUG_PATTERN.match(step.slug):
            findings.append(
                Finding(
                    check_id="identity.slug",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message=f"slug {step.slug!r} does not match slug pattern",
                )
            )
    return findings


def check_identity_concept_id(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check concept identifier pattern conformance."""
    findings: list[Finding] = []
    for concept_id in tree.concept_ids:
        if not CONCEPT_ID_PATTERN.match(concept_id):
            findings.append(
                Finding(
                    check_id="identity.concept_id",
                    severity="error",
                    artifact_path="concept",
                    message=f"concept_id {concept_id!r} does not match C-NNN",
                )
            )
    for step in steps:
        for concept_id in step.concepts:
            if not CONCEPT_ID_PATTERN.match(concept_id):
                findings.append(
                    Finding(
                        check_id="identity.concept_id",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=(
                            f"concept reference {concept_id!r} does not "
                            "match C-NNN"
                        ),
                    )
                )
    return findings


def check_identity_label(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check bare paragraph labels and braced source label syntax."""
    findings: list[Finding] = []
    for label in tree.labels:
        if not isinstance(label, str) or not LABEL_PATTERN.match(label):
            findings.append(
                Finding(
                    check_id="identity.label",
                    severity="error",
                    artifact_path="source_spec.md",
                    message=f"label {label!r} does not match four base36 characters",
                )
            )
    for step in steps:
        for source_label in step.fields.get("source_labels", []):
            if (
                not isinstance(source_label, str)
                or len(source_label) != 6
                or not source_label.startswith("{")
                or not source_label.endswith("}")
                or not LABEL_PATTERN.match(source_label[1:-1])
            ):
                findings.append(
                    Finding(
                        check_id="identity.label",
                        severity="error",
                        artifact_path=_path(tree, step),
                        message=f"source label {source_label!r} is not braced base36",
                    )
                )
    return findings
