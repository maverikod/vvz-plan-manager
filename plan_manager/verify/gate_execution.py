"""Execution-integrity checks for the mechanical gate (EIG block E1, todo 0f50b0df).

EIG block E2 (todo c6f541d0) adds four further closure checks to this same
``execution_integrity`` group, kept in the sibling module
``gate_execution_closure.py`` purely to stay under this file's ~400-line
budget; ``run_all`` below is the single entry point ``gate.py`` dispatches
through so its own call site stays one line no matter how many checks this
group grows to.

Four checks over the extended execution graph (EIG block B,
``views.execution_graph.build_execution_graph``): every INFERRED
``object_producer``/``verification_target`` edge is cross-checked against the
EXPLICIT graph (``views.dependency_graph.build_edges``) and its
explicit-mode parallel waves (``views.dependency_graph.waves``), plus the
combined-graph cycle report ``build_execution_graph`` already computes.

Every check here only ever fires on inferred-edge or dict-shaped
``verification`` data (block-A object roles, AS verification/target_file
pairs). A role-less plan with no such data produces zero inferred edges and
zero cycles (``build_execution_graph`` on a role-less fixture), so all four
checks are silently empty on it -- this is what keeps a legacy plan green
(pinned by ``tests/test_eig_block_e1_gate_execution.py::
test_legacy_role_less_plan_yields_zero_findings_from_all_four_checks``).

The fourth check, ``no_orphan_verification``, was SUPPRESSED through blocks
E1/E2 and is ENFORCED again as of EIG block F (todo 763ae29e), which supplies
the CA file-existence knowledge it always needed -- see
``ORPHAN_VERIFICATION_ENFORCEMENT`` below and the rewritten
``_detect_orphan_verification``. It stays silent unless the caller hands down
an AVAILABLE external file probe, so every probe-less ``run_gate`` caller
sees exactly the pre-block-F behaviour. Block F also adds four further checks
to this same group, in a third module ``gate_execution_existence.py`` (same
~400-line-cap reason), dispatched by the ``run_all`` below.

Resolution universe is always the full plan tree (``tree.steps``), mirroring
``verify.gate_refs.check_references_depends_on``: a branch-scoped gate run
must see the same violation a plan-scoped run does, so graphs, explicit
edges, and waves are all built once over ``tree.steps`` and findings are
then filtered to the branch's own ``steps`` scope by the violating
(consumer/verifier) step's artifact path.

An ambiguous same-file writer order makes ``build_edges``/
``build_execution_graph`` raise ``SameFileOrderAmbiguousError`` (strict by
default). The mechanical gate's own contract is to never raise for this
condition -- ``gate_structure.check_dependencies_same_file_order`` already
surfaces it as a ``dependencies.same_file_order`` finding using
``build_edges(..., strict_same_file_order=False)`` earlier, in the
"references" group -- so the three graph-dependent checks below catch the
same exception and yield zero findings rather than letting it propagate out
of ``run_gate``: a graph analysis built on top of an already-ambiguous
explicit order is not well-defined, and the ambiguity itself is already
reported once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of
from plan_manager.verify.gate_execution_closure import (
    check_deployment_closure,
    check_no_unverified_production,
    check_release_artifact_closure,
    check_test_coverage_present,
)
from plan_manager.verify.gate_execution_existence import (
    run_all as run_existence_checks,
)
from plan_manager.views.dependency_graph import build_edges, waves
from plan_manager.views.execution_graph import build_execution_graph
from plan_manager.views.same_file_order import SameFileOrderAmbiguousError, reachable

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps verify free of the CA transport
    from plan_manager.runtime.ca_files_probe import ExternalFilesProbe

# Enforcement switch for check_no_orphan_verification. It shipped
# "suppressed" through EIG blocks E1/E2 (coordinator order, 2026-08-15): a
# verification.target routinely names a legitimately pre-existing repo file,
# that check had no CA/filesystem access to confirm existence either way, and
# Report.green counts every finding regardless of severity
# (verify.finding.build_report) -- so enforcing it then would have false-redded
# most real plans on deploy. EIG block F (todo 763ae29e) removes the cause
# rather than the check: the caller now hands run_gate a live CA file-existence
# probe, and the detector below only speaks when that probe is present AND
# available. With no probe the check is exactly as silent as it was while
# suppressed, so flipping this switch cannot regress a probe-less caller.
ORPHAN_VERIFICATION_ENFORCEMENT = "enforced"  # flipped by EIG block F


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def check_object_producer_before_consumer(
    tree: GateTree, steps: list[Step]
) -> list[Finding]:
    """Every inferred object_producer edge must already hold in the explicit graph.

    For each INFERRED ``object_producer`` edge (producer -> consumer) of the
    extended execution graph, the EXPLICIT graph (``build_edges``: declared
    depends_on plus deterministic same-file/cross-branch order, no inferred
    edges folded in) must already make the consumer reachable from the
    producer -- the same implication test
    ``commands.execution_dependency_ops.compute_suggested_changes`` uses to
    decide whether an inferred edge still needs to be proposed. A violation
    means nothing in the explicit graph guarantees the producer runs before
    the consumer that reads its object.
    """
    scoped_consumer_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_consumer_paths:
        return []
    try:
        graph = build_execution_graph(tree.steps)
        explicit_edges = build_edges(tree.steps)
    except SameFileOrderAmbiguousError:
        # Already reported once by references.dependencies_same_file_order;
        # a graph analysis on top of an undefined explicit order is not
        # meaningful, and the gate itself must never raise for this.
        return []
    path_to_uuid = {
        artifact_path_of(tree.steps, step): node_uuid
        for node_uuid, step in tree.steps.items()
    }

    findings: list[Finding] = []
    for edge in graph["inferred_edges"]:
        if edge["type"] != "object_producer":
            continue
        consumer_path = edge["to"]
        if consumer_path not in scoped_consumer_paths:
            continue
        producer_path = edge["from"]
        producer_uuid = path_to_uuid[producer_path]
        consumer_uuid = path_to_uuid[consumer_path]
        if reachable(explicit_edges, producer_uuid, consumer_uuid):
            continue
        object_name = edge["evidence"]["object"]
        candidates = sorted(
            {
                other["from"]
                for other in graph["inferred_edges"]
                if other["type"] == "object_producer"
                and other["to"] == consumer_path
                and other["evidence"]["object"] == object_name
            }
        )
        findings.append(
            Finding(
                check_id="execution_integrity.object_producer_before_consumer",
                severity="error",
                artifact_path=consumer_path,
                message=(
                    f"EXEC_PRODUCER_UNORDERED: step_path={consumer_path!r}; "
                    f"object={object_name!r}; expected_producer={producer_path!r}; "
                    f"candidates={candidates!r}; reason='producer is not ordered "
                    "before consumer by any explicit dependency, same-file "
                    "priority, or cross-branch inference; add the missing order "
                    "via execution_dependency_suggest/execution_dependency_apply'"
                ),
            )
        )
    return findings


def check_execution_graph_acyclic(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """The combined explicit+inferred execution graph must have no cycle.

    Reuses ``build_execution_graph``'s own cycle report (Tarjan SCCs over
    the combined edge set, one concrete ordered path per cycle). A cycle is
    reported when it is only visible once inferred edges are folded in, so
    this check can fire on a plan whose EXPLICIT graph is (and must always
    be, by write-time refusal) acyclic on its own.
    """
    try:
        graph = build_execution_graph(tree.steps)
    except SameFileOrderAmbiguousError:
        return []
    if not graph["cycles"]:
        return []
    scoped_paths = {_path(tree, s) for s in steps}
    findings: list[Finding] = []
    for cycle in graph["cycles"]:
        if not any(path in scoped_paths for path in cycle):
            continue
        findings.append(
            Finding(
                check_id="execution_integrity.execution_graph_acyclic",
                severity="error",
                artifact_path=cycle[0],
                message=(
                    f"EXEC_GRAPH_CYCLE: path={cycle!r}; reason='the combined "
                    "explicit+inferred execution graph contains a cycle "
                    "through this ordered path'"
                ),
            )
        )
    return findings


def check_parallelization_safe(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """No inferred edge's endpoints may share one explicit-mode wave.

    For every INFERRED edge (``object_producer`` or ``verification_target``),
    the EXPLICIT-mode waves (``waves(nodes, build_edges(nodes))``, the same
    partition a wave-parallel executor would follow with no inferred edges
    applied) must not place producer and consumer in the SAME wave: that
    would let a parallel executor run them concurrently even though one
    reads what the other writes or verifies. Deliberately overlaps
    ``object_producer_before_consumer`` on the object_producer family (an
    unordered pair very often also lands same-wave) -- this check is
    wave-specific and additionally covers ``verification_target`` edges,
    which the reachability check does not.
    """
    scoped_consumer_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_consumer_paths:
        return []
    try:
        graph = build_execution_graph(tree.steps)
        explicit_edges = build_edges(tree.steps)
        explicit_waves = waves(tree.steps, explicit_edges)
    except SameFileOrderAmbiguousError:
        return []
    wave_of = {
        node_uuid: index
        for index, wave in enumerate(explicit_waves)
        for node_uuid in wave
    }
    path_to_uuid = {
        artifact_path_of(tree.steps, step): node_uuid
        for node_uuid, step in tree.steps.items()
    }

    findings: list[Finding] = []
    for edge in graph["inferred_edges"]:
        if edge["type"] not in ("object_producer", "verification_target"):
            continue
        consumer_path = edge["to"]
        if consumer_path not in scoped_consumer_paths:
            continue
        producer_path = edge["from"]
        producer_uuid = path_to_uuid[producer_path]
        consumer_uuid = path_to_uuid[consumer_path]
        producer_wave = wave_of[producer_uuid]
        consumer_wave = wave_of[consumer_uuid]
        if producer_wave != consumer_wave:
            continue
        findings.append(
            Finding(
                check_id="execution_integrity.parallelization_safe",
                severity="error",
                artifact_path=consumer_path,
                message=(
                    f"EXEC_PARALLEL_UNSAFE: step_path={consumer_path!r}; "
                    f"expected_producer={producer_path!r}; edge_type={edge['type']!r}; "
                    f"candidates={[producer_path]!r}; wave={consumer_wave!r}; "
                    "reason='producer and consumer share one explicit-mode wave "
                    "with no explicit order between them; a parallel executor "
                    "could run them concurrently -- add an explicit dependency'"
                ),
            )
        )
    return findings


def check_no_orphan_verification(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
) -> list[Finding]:
    """An AS's verification.target must exist externally or be a plan target_file.

    ENFORCED since EIG block F (see ``ORPHAN_VERIFICATION_ENFORCEMENT``), but
    only ever speaks when ``external_files`` is an AVAILABLE probe: a probe of
    ``None`` (no project binding, or a caller that does not wire one -- every
    ``run_gate`` caller except plan_validate, block-G residual) and an
    unavailable probe both yield ``[]``, the same silence the suppressed
    check had.

    This check_id is the SINGLE reporting site for the "does the verified
    file exist anywhere" question. Block F's own
    ``execution_integrity.verification_target_resolvable`` asks exactly the
    same question and is therefore MERGED into this one detector: it stays
    registered for report-shape stability but is permanently empty, and its
    code ``VERIFICATION_ARTIFACT_MISSING`` is never emitted -- see
    ``gate_execution_existence.check_verification_target_resolvable``.
    """
    if ORPHAN_VERIFICATION_ENFORCEMENT == "suppressed":
        return []
    return _detect_orphan_verification(tree, steps, external_files)


def _detect_orphan_verification(
    tree: GateTree,
    steps: list[Step],
    external_files: "ExternalFilesProbe | None" = None,
) -> list[Finding]:
    """Raw detector for check_no_orphan_verification, in block-F semantics.

    A dict-form ``verification.target`` is an ORPHAN only when BOTH sources
    of existence fail it: it is absent from the live project file inventory
    (``external_files.files``) AND it matches no atomic step's
    ``target_file`` anywhere in the FULL plan tree. Severity is ERROR now
    (it was WARNING while the pre-block-F detector could only guess): with
    the probe available, "this file exists nowhere" is a fact, not a
    suspicion.

    Returns ``[]`` when the probe is missing or unavailable -- the degraded
    policy shared with ``gate_execution_existence`` (see its module
    docstring's matrix); an unreadable project never turns into per-step
    verdicts. It only ever fires on a dict-shaped ``verification`` field
    with a non-empty ``target``, so a legacy plan (string-shaped or absent
    verification) yields zero findings from it even with a probe present,
    same as the other three E1 checks.
    """
    if external_files is None or not external_files.available:
        return []
    known_files = external_files.files
    target_files: set[str] = set()
    for step in tree.steps.values():
        if step.level != 5:
            continue
        target_file = step.fields.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            target_files.add(target_file.strip())

    findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        verification = step.fields.get("verification")
        if not isinstance(verification, dict):
            continue
        target = verification.get("target")
        if not isinstance(target, str) or not target.strip():
            continue
        target = target.strip()
        if target in known_files or target in target_files:
            continue
        path = _path(tree, step)
        findings.append(
            Finding(
                check_id="execution_integrity.no_orphan_verification",
                severity="error",
                artifact_path=path,
                message=(
                    f"EXEC_ORPHAN_VERIFICATION: step_path={path!r}; target={target!r}; "
                    "reason='verification target exists neither in the bound "
                    "project (live analysis-server file listing) nor as any "
                    "target_file declared anywhere in the plan; this step "
                    "verifies a file nothing produces and nothing already has'"
                ),
            )
        )
    return findings


def run_all(
    tree: GateTree,
    steps: list[Step],
    *,
    external_files: "ExternalFilesProbe | None" = None,
    require_project_verification: bool = False,
) -> list[Finding]:
    """Run all twelve execution_integrity checks (EIG blocks E1 + E2 + F), in CHECK_IDS order.

    ``gate.py`` dispatches the whole "execution_integrity" group through
    this single call so its own execution_integrity call site stays one
    line regardless of how many checks the group grows to: E1's four checks
    (above, this module), E2's four closure checks
    (``gate_execution_closure.py``), and block F's four existence checks
    (``gate_execution_existence.py``), concatenated in the same order they
    are registered in ``gate.CHECK_IDS["execution_integrity"]``.

    ``external_files`` is the live CA project-file probe the CALLER fetched
    (the gate never performs I/O); ``require_project_verification`` is the
    operator policy that decides whether an UNAVAILABLE probe is itself a
    finding. Both default to the degraded-but-silent case, so every existing
    caller keeps exactly its pre-block-F behaviour.
    """
    findings: list[Finding] = []
    findings.extend(check_object_producer_before_consumer(tree, steps))
    findings.extend(check_execution_graph_acyclic(tree, steps))
    findings.extend(check_parallelization_safe(tree, steps))
    findings.extend(check_no_orphan_verification(tree, steps, external_files))
    findings.extend(check_test_coverage_present(tree, steps))
    findings.extend(check_release_artifact_closure(tree, steps))
    findings.extend(check_deployment_closure(tree, steps))
    findings.extend(check_no_unverified_production(tree, steps))
    findings.extend(
        run_existence_checks(
            tree, steps, external_files, require_project_verification
        )
    )
    return findings
