"""Execution-integrity closure checks for the mechanical gate (EIG block E2, todo c6f541d0).

Four further checks in the same ``execution_integrity`` group as
``verify.gate_execution`` (EIG block E1), split into this second module
purely to keep ``gate_execution.py`` under its ~400-line cap -- both modules
are dispatched together by ``gate_execution.run_all`` and registered as one
group in ``gate.CHECK_IDS["execution_integrity"]``.

Where E1 cross-checks the INFERRED object_producer/verification_target
edges (``views.execution_graph.build_execution_graph``) against the
EXPLICIT graph, E2 reads block-A object ROLES directly (``domain.
step_objects.OBJECT_ROLES``: create, modify, consume, verify, document,
package, deploy) and asks a narrower question per role family: is every
producing/shipping declaration matched by a verification declaration, and
is that verification ordered after production in the explicit graph
(``views.dependency_graph.build_edges`` plus ``views.same_file_order.
reachable``, never the inferred graph)?

Every check below is a no-op the moment the plan does not use the role it
keys off -- the same "legacy plan stays green" discipline E1 established
(see its module docstring). ``check_test_coverage_present`` additionally
applies an OPT-IN rule on top of that: it only ever fires once the plan has
declared at least one verify-role object ANYWHERE, i.e. the plan has
already opted into test-coverage discipline for at least one object. A
plan that uses create/modify roles but never uses the verify role at all
(no test-coverage discipline adopted yet) gets zero findings from this
check rather than being red-flagged for every single producer -- that
blanket red would be indistinguishable from noise and would punish a plan
that simply has not adopted verify-role declarations yet, exactly the E1
lesson (never red a legacy or role-less plan). ``check_no_unverified_
production`` is deliberately NOT opt-in: declaring a package or deploy
role on an object *is itself* the opt-in signal (shipping the object at
all), so a missing verify-role declaration for that object fires
unconditionally.

Resolution universe is always the full plan tree (``tree.steps``), and
findings are filtered to the branch's own ``steps`` scope by the
violating step's artifact path, mirroring ``gate_execution.py`` exactly
(see its module docstring for the branch-scope rationale).

Same ambiguity-tolerance contract as E1: ``build_edges`` raising
``SameFileOrderAmbiguousError`` on an undefined same-file writer order is
caught and turned into zero findings from the two ordering-dependent
checks below (``check_release_artifact_closure``,
``check_deployment_closure``) -- the ambiguity itself is already reported
once by ``gate_structure.check_dependencies_same_file_order``.
"""

from __future__ import annotations

from uuid import UUID

from plan_manager.domain.step import Step
from plan_manager.domain.step_objects import normalize_as_object_declarations
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.same_file_order import SameFileOrderAmbiguousError, reachable


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def _object_role_declarations(tree: GateTree) -> dict[str, dict[str, list[Step]]]:
    """Map object name -> role -> declaring level-5 steps, over the full plan tree.

    A sibling accumulation to ``views.execution_graph._object_roles``, but
    keeping every declaring step per (object, role) pair instead of
    collapsing to one artifact path per role: the checks below need to walk
    each individual declaring step (to name it in a finding, to order it in
    the explicit graph by its uuid), not just know a role is present
    somewhere. Role-less entries (legacy plain-string objects, or dict
    entries with no "role" key) are skipped entirely -- exactly like
    ``_object_roles`` -- so a role-less plan yields an empty map and every
    check below is a no-op on it.
    """
    result: dict[str, dict[str, list[Step]]] = {}
    for step in tree.steps.values():
        if step.level != 5:
            continue
        declarations, _problems = normalize_as_object_declarations(
            step.fields or {}, allow_legacy_strings=True
        )
        for declaration in declarations:
            role = declaration.get("role")
            if role is None:
                continue
            name = declaration["name"]
            result.setdefault(name, {}).setdefault(role, []).append(step)
    return result


def _producer_steps(roles: dict[str, list[Step]]) -> dict[UUID, Step]:
    """Union of an object's create/modify declaring steps, deduplicated by uuid."""
    producers: dict[UUID, Step] = {}
    for role in ("create", "modify"):
        for step in roles.get(role, []):
            producers[step.uuid] = step
    return producers


def check_test_coverage_present(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Every create/modify-role object must also carry a verify-role declaration.

    OPT-IN (see module docstring): fires only once the plan has declared at
    least one verify-role object anywhere; a plan that has never used the
    verify role at all gets zero findings from this check. Once opted in,
    every object declared with role create or modify by some AS, that is
    NOWHERE also declared with role verify by any AS, is flagged on each of
    its producer (create/modify) steps.
    """
    role_map = _object_role_declarations(tree)
    if not any("verify" in roles for roles in role_map.values()):
        return []
    scoped_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_paths:
        return []

    findings: list[Finding] = []
    for name in sorted(role_map):
        roles = role_map[name]
        if "verify" in roles:
            continue
        producers = _producer_steps(roles)
        if not producers:
            continue
        for producer in sorted(producers.values(), key=lambda s: _path(tree, s)):
            producer_path = _path(tree, producer)
            if producer_path not in scoped_paths:
                continue
            findings.append(
                Finding(
                    check_id="execution_integrity.test_coverage_present",
                    severity="error",
                    artifact_path=producer_path,
                    message=(
                        f"EXEC_TEST_COVERAGE_MISSING: step_path={producer_path!r}; "
                        f"object={name!r}; reason='no verify-role declaration for "
                        "this object anywhere in the plan; add a verify-role "
                        "object declaration on some AS (existing or new) that "
                        "checks this object'"
                    ),
                )
            )
    return findings


def check_release_artifact_closure(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """A package-role object's verify-role declarations must be ordered after it.

    For every object with role package declared by some step P, every
    verify-role declaration of the SAME object must be reachable-after P in
    the EXPLICIT graph (``build_edges``, never the inferred graph): a
    verifier that is not ordered after every one of the object's
    package-role declarations could run before the artifact it verifies is
    even built. Zero package-role declarations anywhere -> zero findings.
    """
    role_map = _object_role_declarations(tree)
    if not any("package" in roles for roles in role_map.values()):
        return []
    scoped_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_paths:
        return []
    try:
        explicit_edges = build_edges(tree.steps)
    except SameFileOrderAmbiguousError:
        return []

    findings: list[Finding] = []
    for name in sorted(role_map):
        roles = role_map[name]
        packagers = roles.get("package", [])
        verifiers = roles.get("verify", [])
        if not packagers or not verifiers:
            continue
        for verifier in sorted(verifiers, key=lambda s: _path(tree, s)):
            verifier_path = _path(tree, verifier)
            if verifier_path not in scoped_paths:
                continue
            unordered_from = [
                packager
                for packager in packagers
                if not reachable(explicit_edges, packager.uuid, verifier.uuid)
            ]
            if not unordered_from:
                continue
            expected = sorted(_path(tree, p) for p in unordered_from)
            findings.append(
                Finding(
                    check_id="execution_integrity.release_artifact_closure",
                    severity="error",
                    artifact_path=verifier_path,
                    message=(
                        f"EXEC_RELEASE_BEFORE_BUILD: step_path={verifier_path!r}; "
                        f"object={name!r}; expected_producer={expected!r}; "
                        "reason='verification is not ordered after every "
                        "package-role declaration of this object in the "
                        "explicit graph -- the build artifact would be verified "
                        "before it is built; add the missing explicit "
                        "dependency'"
                    ),
                )
            )
    return findings


def check_deployment_closure(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """A deploy-role object must be produced by something and verified after it deploys.

    For every object with role deploy declared by some step D: (a) every
    verify-role declaration of the same object must be reachable-after D in
    the explicit graph, mirroring ``check_release_artifact_closure``; (b) if
    the object has NO producing create/modify/package declaration anywhere
    in the plan, D itself is flagged (deploying an artifact nothing
    produces). Note that (b) is naturally suppressed when D's own step also
    declares create or package for the same object, since that declaration
    is itself a producing declaration "anywhere in the plan" -- no separate
    special case is needed. Zero deploy-role declarations anywhere -> zero
    findings.
    """
    role_map = _object_role_declarations(tree)
    if not any("deploy" in roles for roles in role_map.values()):
        return []
    scoped_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_paths:
        return []
    try:
        explicit_edges = build_edges(tree.steps)
    except SameFileOrderAmbiguousError:
        return []

    findings: list[Finding] = []
    for name in sorted(role_map):
        roles = role_map[name]
        deployers = roles.get("deploy", [])
        if not deployers:
            continue
        verifiers = roles.get("verify", [])
        producers = _producer_steps(roles)
        for role in ("package",):
            for step in roles.get(role, []):
                producers.setdefault(step.uuid, step)

        for verifier in sorted(verifiers, key=lambda s: _path(tree, s)):
            verifier_path = _path(tree, verifier)
            if verifier_path not in scoped_paths:
                continue
            unordered_from = [
                deployer
                for deployer in deployers
                if not reachable(explicit_edges, deployer.uuid, verifier.uuid)
            ]
            if not unordered_from:
                continue
            expected = sorted(_path(tree, d) for d in unordered_from)
            findings.append(
                Finding(
                    check_id="execution_integrity.deployment_closure",
                    severity="error",
                    artifact_path=verifier_path,
                    message=(
                        f"EXEC_DEPLOY_CLOSURE: step_path={verifier_path!r}; "
                        f"object={name!r}; expected_producer={expected!r}; "
                        "reason='verification is not ordered after every "
                        "deploy-role declaration of this object in the "
                        "explicit graph; add the missing explicit dependency'"
                    ),
                )
            )

        if producers:
            continue
        for deployer in sorted(deployers, key=lambda s: _path(tree, s)):
            deployer_path = _path(tree, deployer)
            if deployer_path not in scoped_paths:
                continue
            findings.append(
                Finding(
                    check_id="execution_integrity.deployment_closure",
                    severity="error",
                    artifact_path=deployer_path,
                    message=(
                        f"EXEC_DEPLOY_CLOSURE: step_path={deployer_path!r}; "
                        f"object={name!r}; reason='deploy-role declaration names "
                        "an object with no create/modify/package-role "
                        "declaration anywhere in the plan; nothing in the plan "
                        "produces what this step deploys'"
                    ),
                )
            )
    return findings


def check_no_unverified_production(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """A package or deploy-role object must carry a verify-role declaration.

    Deliberately NOT opt-in (unlike ``check_test_coverage_present``):
    declaring package or deploy for an object IS itself the opt-in signal
    (shipping the object at all), so a missing verify-role declaration for
    that object is flagged unconditionally, on every one of its
    package/deploy-role declaring steps. Overlaps
    ``check_test_coverage_present`` by design: that check covers
    create/modify under the opt-in rule, this one covers package/deploy
    unconditionally. Zero package/deploy-role declarations anywhere -> zero
    findings.
    """
    role_map = _object_role_declarations(tree)
    scoped_paths = {_path(tree, s) for s in steps if s.level == 5}
    if not scoped_paths:
        return []

    findings: list[Finding] = []
    for name in sorted(role_map):
        roles = role_map[name]
        if "verify" in roles:
            continue
        declarers: dict[UUID, Step] = {}
        for role in ("package", "deploy"):
            for step in roles.get(role, []):
                declarers[step.uuid] = step
        if not declarers:
            continue
        for declarer in sorted(declarers.values(), key=lambda s: _path(tree, s)):
            declarer_path = _path(tree, declarer)
            if declarer_path not in scoped_paths:
                continue
            findings.append(
                Finding(
                    check_id="execution_integrity.no_unverified_production",
                    severity="error",
                    artifact_path=declarer_path,
                    message=(
                        f"EXEC_UNVERIFIED_PRODUCTION: step_path={declarer_path!r}; "
                        f"object={name!r}; reason='object carries a package or "
                        "deploy-role declaration with no verify-role "
                        "declaration anywhere in the plan; production/"
                        "deployment without any declared verification path'"
                    ),
                )
            )
    return findings
