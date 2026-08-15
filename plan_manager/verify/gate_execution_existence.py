"""CA-backed existence checks for the mechanical gate (EIG block F, todo 763ae29e).

Blocks E1/E2 could only ever compare the plan against ITSELF: every
execution_integrity check so far asks whether one declaration is ordered
after, or matched by, another declaration in the same plan. Neither block had
any knowledge of what already exists in the project the plan is bound to,
which is exactly why ``gate_execution.check_no_orphan_verification`` shipped
SUPPRESSED -- a verification target naming a legitimately pre-existing repo
file was indistinguishable from one naming nothing at all.

Block F supplies that missing half as an EXTERNAL FILE PROBE
(``runtime.ca_files_probe.ExternalFilesProbe``): the live project-relative
file inventory of the plan's primary analysis-server project, fetched by the
CALLER (``commands.plan_validate_command``) and handed down to ``run_gate``.
The gate itself stays sync and pure -- nothing in ``verify`` performs I/O, and
this module does not even import the CA transport (the probe type is imported
under ``TYPE_CHECKING`` only, and the value is used structurally).

DEGRADED POLICY -- the single rule every check below obeys:

===================== ============================ =========================
probe                 require_project_verification  emitted
===================== ============================ =========================
None                  either                        nothing at all
available=False       False                         nothing at all
available=False       True                          exactly ONE
                                                    external_project_unverified
available=True        either                        the real findings
===================== ============================ =========================

"probe is None" means the caller had no primary project binding to probe, or
did not wire a probe at all (every ``run_gate`` caller other than
plan_validate, this block -- block-G residual). Absence of knowledge is never
a violation: a plan that cannot be checked against a project is silently
exempt unless the operator has opted into ``require_project_verification``,
in which case the single plan-level finding says so explicitly instead of
inventing per-step verdicts from a probe that failed.

THE ARTIFACT_PRODUCER / MODIFY_CONTEXT SPLIT. Both checks look at exactly the
same population -- an AS whose ``operation`` is ``modify_file`` and whose
``target_file`` is NOT in the probe's inventory -- and are produced by ONE
scan (``_scan_modify_targets``) so they can never both fire for one
(step, file) pair. The split is on WHY the file is unavailable:

- no ``create_file`` owner of that path anywhere in the plan -> TOTAL
  ABSENCE: nothing outside the plan has the file and nothing inside it ever
  creates it, so no execution context can ever carry the file's current
  content to the executor ->
  ``modify_file_context_available`` / ``EXEC_MODIFY_TARGET_MISSING``.
- some ``create_file`` owner exists in-plan but none of them is ordered
  before this step in the EXPLICIT graph -> ORDERING: the content will exist
  eventually, just not necessarily yet ->
  ``artifact_producer_exists`` / ``EXEC_ARTIFACT_PRODUCER_MISSING``.

Same ambiguity tolerance as E1/E2: ``build_edges`` raising
``SameFileOrderAmbiguousError`` (already reported once by
``gate_structure.check_dependencies_same_file_order``) suppresses only the
ORDERING half -- total absence needs no graph and is still reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.same_file_order import SameFileOrderAmbiguousError, reachable

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps verify free of the CA transport
    from plan_manager.runtime.ca_files_probe import ExternalFilesProbe


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def _creators_by_file(tree: GateTree) -> dict[str, list[Step]]:
    """Map target_file -> the level-5 steps that CREATE it, over the full tree.

    Only ``operation == "create_file"`` counts as producing a file that did
    not exist before, mirroring ``views.execution_graph.
    _verification_target_edges``'s creator rule exactly: a ``modify_file``
    owner presupposes the file, it does not bring it into existence.
    """
    creators: dict[str, list[Step]] = {}
    for step in tree.steps.values():
        if step.level != 5:
            continue
        if step.fields.get("operation") != "create_file":
            continue
        target_file = step.fields.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            creators.setdefault(target_file.strip(), []).append(step)
    return creators


def _scan_modify_targets(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None",
) -> tuple[list[Finding], list[Finding]]:
    """One pass over the scoped modify_file steps, two disjoint finding kinds.

    Returns ``(artifact_producer_exists findings, modify_file_context_available
    findings)``. A given (step, target_file) pair contributes to at most one
    of the two lists -- see the module docstring for the split rule. Both are
    empty whenever the probe is missing or unavailable (degraded policy).
    """
    if external_files is None or not external_files.available:
        return [], []
    known_files = external_files.files
    creators = _creators_by_file(tree)
    try:
        explicit_edges = build_edges(tree.steps)
    except SameFileOrderAmbiguousError:
        # Only the ordering half is undefined; total absence still holds.
        explicit_edges = None

    producer_findings: list[Finding] = []
    context_findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        if step.fields.get("operation") != "modify_file":
            continue
        target_file = step.fields.get("target_file")
        if not isinstance(target_file, str) or not target_file.strip():
            continue
        target_file = target_file.strip()
        if target_file in known_files:
            continue
        owners = [
            creator
            for creator in creators.get(target_file, [])
            if creator.uuid != step.uuid
        ]
        path = _path(tree, step)
        if not owners:
            context_findings.append(
                Finding(
                    check_id="execution_integrity.modify_file_context_available",
                    severity="error",
                    artifact_path=path,
                    message=(
                        f"EXEC_MODIFY_TARGET_MISSING: step_path={path!r}; "
                        f"target_file={target_file!r}; reason='this step modifies a "
                        "file that exists neither in the bound project (live "
                        "analysis-server file listing) nor as a create_file "
                        "declaration anywhere in the plan; no execution context "
                        "can carry its current content to the executor'"
                    ),
                )
            )
            continue
        if explicit_edges is None:
            continue
        if any(reachable(explicit_edges, owner.uuid, step.uuid) for owner in owners):
            continue
        expected = sorted(_path(tree, owner) for owner in owners)
        producer_findings.append(
            Finding(
                check_id="execution_integrity.artifact_producer_exists",
                severity="error",
                artifact_path=path,
                message=(
                    f"EXEC_ARTIFACT_PRODUCER_MISSING: step_path={path!r}; "
                    f"target_file={target_file!r}; expected_producer={expected!r}; "
                    "reason='this step modifies a file absent from the bound "
                    "project, and no in-plan create_file owner of it is ordered "
                    "before this step in the explicit graph; add the missing "
                    "explicit dependency'"
                ),
            )
        )
    return producer_findings, context_findings


def check_artifact_producer_exists(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
) -> list[Finding]:
    """A modify_file target must exist externally or be created before this step.

    The ORDERING half of the shared scan (module docstring): fires only when
    the file is absent from the probe's inventory AND some in-plan
    ``create_file`` owner exists but none is reachable-before this step in
    the explicit graph. Total absence is reported by
    ``check_modify_file_context_available`` instead, never by both.
    ``run_all`` runs the scan once and takes both halves; this entry point
    exists so the check can be exercised on its own.
    """
    producer_findings, _context_findings = _scan_modify_targets(
        tree, steps, external_files
    )
    return producer_findings


def check_modify_file_context_available(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
) -> list[Finding]:
    """A modify_file target that exists NOWHERE has no obtainable context.

    The TOTAL-ABSENCE half of the shared scan (module docstring): the file is
    in neither the bound project's live listing nor any in-plan
    ``create_file`` declaration, so the executor can never be handed its
    current content. Detected by the same pass as
    ``check_artifact_producer_exists`` but reported under its own check_id
    and code (``EXEC_MODIFY_TARGET_MISSING``) so the report names the
    executor-context consequence rather than an ordering defect; the two are
    mutually exclusive per (step, file).
    """
    _producer_findings, context_findings = _scan_modify_targets(
        tree, steps, external_files
    )
    return context_findings


def check_verification_target_resolvable(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
) -> list[Finding]:
    """MERGED into no_orphan_verification -- permanently empty, still registered.

    Block F's design named two checks for one question: whether an AS's
    dict-form ``verification.target`` resolves to a file that exists in the
    bound project or is produced by some in-plan ``target_file``. That is
    literally the block-F semantics of ``gate_execution.
    _detect_orphan_verification``, which this block re-enables. Running both
    would report every violation twice under two check_ids.

    The merge decision is therefore: ONE detector
    (``gate_execution._detect_orphan_verification``), reporting under
    ``execution_integrity.no_orphan_verification``; this check_id stays
    REGISTERED in ``gate.CHECK_IDS`` for report-shape stability and always
    reports passed=true with zero findings. Its would-be code
    ``VERIFICATION_ARTIFACT_MISSING`` is consequently never emitted -- read
    ``EXEC_ORPHAN_VERIFICATION`` findings instead. See the twin note in
    ``gate_execution.check_no_orphan_verification``.
    """
    return []


def check_external_project_unverified(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
    require_project_verification: bool = False,
) -> list[Finding]:
    """Under an opt-in policy, an unverifiable project is itself a finding.

    Emits exactly ONE plan-level finding, and only when the caller DID hand
    down a probe that came back unavailable AND the operator has set
    ``code_analysis.require_project_verification``. Every other cell of the
    degraded matrix (module docstring) emits nothing: no probe at all is not
    a policy violation, and an unavailable probe under the default policy
    degrades silently exactly as blocks E1/E2 did.

    ``artifact_path`` is ``"plan"`` rather than a step path on purpose: the
    condition is a property of the run (the project could not be read), not
    of any one step, so branch-scoped and plan-scoped runs report it
    identically.
    """
    if external_files is None or external_files.available:
        return []
    if not require_project_verification:
        return []
    return [
        Finding(
            check_id="execution_integrity.external_project_unverified",
            severity="error",
            artifact_path="plan",
            message=(
                f"EXEC_EXTERNAL_PROJECT_UNVERIFIED: reason={external_files.reason!r}; "
                "reason_detail='code_analysis.require_project_verification is "
                "enabled but the bound project's file listing could not be read "
                "from the analysis server, so no existence check could run; "
                "fix the CA configuration/connectivity or disable the policy'"
            ),
        )
    ]


def run_all(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
    require_project_verification: bool = False,
) -> list[Finding]:
    """Run block F's four checks in ``CHECK_IDS["execution_integrity"]`` order.

    Runs ``_scan_modify_targets`` ONCE and splits its two halves into the
    artifact_producer_exists and modify_file_context_available check_ids,
    rather than calling the two public single-check entry points (which
    would repeat the scan).
    """
    producer_findings, context_findings = _scan_modify_targets(
        tree, steps, external_files
    )
    findings: list[Finding] = []
    findings.extend(producer_findings)
    findings.extend(check_verification_target_resolvable(tree, steps, external_files))
    findings.extend(context_findings)
    findings.extend(
        check_external_project_unverified(
            tree, steps, external_files, require_project_verification
        )
    )
    return findings
