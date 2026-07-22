"""Parse and identity checks for the mechanical gate (C-012)."""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from plan_manager.domain.concept import CONCEPT_ID_PATTERN
from plan_manager.domain.step import SLUG_PATTERN, STEP_ID_PATTERNS, Step, validate_ts_inputs_outputs
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
    """Check structured tactical inputs and outputs.

    Delegates the nested {name, type, description} item schema (including
    the type enum "input"/"output") to the shared
    plan_manager.domain.step.validate_ts_inputs_outputs validator, the same
    single source of truth enforced at the step_update and layout_import
    write boundaries (bug 26fa21a5). This check remains the read-time
    reporting surface; the write boundaries now reject the payload before
    it ever reaches here.
    """
    findings: list[Finding] = []
    for step in steps:
        if step.level != 4:
            continue
        for problem in validate_ts_inputs_outputs(step.fields):
            findings.append(
                Finding(
                    check_id="parse.inputs_outputs",
                    severity="error",
                    artifact_path=_path(tree, step),
                    message=problem["message"],
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
    r"\b(?:create|write|modify|edit|update|replace|delete|remove|rename|move|patch|append|insert|touch|change|alter|"
    r"создать|создай|записать|изменить|изменять|изменяй|редактировать|редактируй|удалить|удалять|удаляй|"
    r"переименовать|переименовывать|переместить|перемещать|добавить|добавлять)\b",
    re.IGNORECASE,
)
# Negation cues that, anywhere in a clause, defeat that clause's write intent
# regardless of which write verb the clause also contains -- covers pre-verb
# negation ("do not modify", "не изменяй") and the "without/без <doing>" form
# ("without changing it") without needing per-verb gerund matching: the cue's
# mere presence in the same (already fine-grained, see _CLAUSE_SPLIT_RE)
# clause is enough to void that clause's write verdict (bug 5ebe3ce5).
_NEGATION_CUE_RE = re.compile(
    r"\b(?:do\s+not|does\s+not|did\s+not|don't|doesn't|didn't|"
    r"must\s+not|should\s+not|shall\s+not|will\s+not|won't|"
    r"cannot|can't|never|without|"
    r"не|нельзя|никогда|без)\b",
    re.IGNORECASE,
)
# Explicit read-only / reference-only framing that also defeats a clause's
# write intent even with no negation word present -- covers phrasing like
# "reuse conventions from X" or "X as a pattern" where X is named purely as
# a read-only reference, plus a bare "read" verb clause (bug 5ebe3ce5).
_READ_ONLY_MARKER_RE = re.compile(
    r"\b(?:"
    r"read-only|reference\s+only|for\s+reference|for\s+comparison|"
    r"as\s+a\s+(?:pattern|reference|template|guide|example)|"
    r"reus\w*\s+conventions?\s+from|"
    r"(?:leave|left|remains?|stays?)\s+(?:it\s+)?unchanged|"
    r"unchanged|"
    r"read"
    r")\b",
    re.IGNORECASE,
)
# Clause boundaries finer than plain sentence splits: also break on commas
# and on contrastive conjunctions (English + Russian), so a single sentence
# mixing a genuine write instruction with a negated/read-only reference to
# another path ("Update A, don't touch B" / "do not modify B but DO update
# C") is judged clause-by-clause instead of as one whole-segment verdict
# (bug 5ebe3ce5 -- the prior whole-segment approach let any write verb
# anywhere in the segment claim every path in it, negated or not).
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[.!?;])\s+"
    r"|\n+"
    r"|\s*,\s+"
    r"|\s+(?:but|however|while|whereas|yet|но|однако|зато)\s+",
    re.IGNORECASE,
)


def _normal_path(value: str) -> str:
    return PurePosixPath(value.strip("`'\".,:;()[]{}<> ")).as_posix()


def _clause_commands_write(clause: str) -> bool:
    """Return True iff `clause` carries unnegated, non-read-only write intent.

    A clause commands a write only when it contains a write-intent verb AND
    contains neither a negation cue (_NEGATION_CUE_RE) nor an explicit
    read-only/reference framing marker (_READ_ONLY_MARKER_RE); either one
    voids the verb match for this clause (bug 5ebe3ce5).
    """
    if _NEGATION_CUE_RE.search(clause) or _READ_ONLY_MARKER_RE.search(clause):
        return False
    return bool(_WRITE_INTENT_RE.search(clause))


@dataclass(frozen=True)
class WriteTargetHit:
    """One code path found on a commanded-write clause of a step field.

    Attributes:
        field_name: The step field ("prompt"/"verification"/"operation")
            the clause was read from.
        path: The normalized project-relative path named in the clause.
        clause: The exact clause text the path was extracted from (its
            source span), already stripped of leading/trailing whitespace.
    """

    field_name: str
    path: str
    clause: str


def _additional_write_target_hits(step: Step, target_file: str) -> list[WriteTargetHit]:
    """Return every additional (non-target) code path on a commanded-write
    clause across the step's prompt/verification/operation fields.

    Each field's text is split into clauses (_CLAUSE_SPLIT_RE: sentence
    boundaries, newlines, commas, and contrastive conjunctions) so a single
    sentence mixing a real write instruction with a negated or read-only
    reference to another path is judged clause-by-clause rather than as one
    whole-segment verdict. A path is a hit only when its clause commands a
    write (_clause_commands_write) and the path differs from `target_file`.
    Hits are de-duplicated by (field_name, path), keeping the first clause
    span encountered, and returned in field-then-first-seen order.
    """
    normalized_target = _normal_path(target_file)
    hits: list[WriteTargetHit] = []
    seen: set[tuple[str, str]] = set()
    for field_name in ("prompt", "verification", "operation"):
        value = step.fields.get(field_name)
        if not isinstance(value, str):
            continue
        for raw_clause in _CLAUSE_SPLIT_RE.split(value):
            clause = raw_clause.strip()
            if not clause or not _clause_commands_write(clause):
                continue
            for raw_path in _CODE_PATH_RE.findall(clause):
                path = _normal_path(raw_path)
                if path == normalized_target:
                    continue
                key = (field_name, path)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(WriteTargetHit(field_name=field_name, path=path, clause=clause))
    return hits


def _additional_write_targets(step: Step, target_file: str) -> dict[str, list[str]]:
    """Return explicit code paths mentioned on commanded-write clauses, by field.

    A thin path-only projection of _additional_write_target_hits, kept as
    its own function because it is the stable shape existing unit tests and
    callers pin: {field_name: sorted unique additional write-target paths}.
    A path mentioned only under negated ("do not modify X") or read-only
    ("reuse conventions from X", "X as a reference") intent is never
    included (bug 5ebe3ce5); a genuinely commanded second write still is.
    """
    result: dict[str, set[str]] = {}
    for hit in _additional_write_target_hits(step, target_file):
        result.setdefault(hit.field_name, set()).add(hit.path)
    return {field_name: sorted(paths) for field_name, paths in result.items()}


def check_parse_atomic_single_code_file(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Reject an AS that explicitly commands writes to a second code file.

    Uses clause-level intent classification (_additional_write_target_hits)
    so a path mentioned only under negated or read-only intent never counts
    as an additional write target (bug 5ebe3ce5); the finding message keeps
    its prior stable prefix (AS_MULTIPLE_CODE_FILES / target_file=
    / additional_write_targets= / source_fields=) and appends a `spans`
    list carrying, per flagged path, the source field, the exact clause it
    was found on, and its inferred intent.
    """
    findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if not isinstance(target_file, str) or not target_file.strip():
            continue
        hits = _additional_write_target_hits(step, target_file)
        if not hits:
            continue
        paths = sorted({hit.path for hit in hits})
        source_fields = sorted({hit.field_name for hit in hits})
        spans = [
            {
                "field": hit.field_name,
                "path": hit.path,
                "clause": hit.clause,
                "intent": "commanded_write",
            }
            for hit in sorted(hits, key=lambda h: (h.field_name, h.path))
        ]
        findings.append(Finding(
            check_id="parse.atomic_single_code_file",
            severity="error",
            artifact_path=_path(tree, step),
            message=(
                "AS_MULTIPLE_CODE_FILES: target_file="
                f"{target_file!r}; additional_write_targets={paths!r}; "
                f"source_fields={source_fields!r}; spans={spans!r}"
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
