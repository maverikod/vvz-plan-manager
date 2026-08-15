"""Extended execution graph derived view (EIG block B, todo 16853f27).

Composes, over the same node set ``views/dependency_graph.py`` uses
(``load_steps``), the declared/derived dependency edges together with two
INFERRED edge families read off the block-A object roles (``domain/
step_objects.py``): object producer/consumer pairs and target-file/
verification-target pairs. Every function here is a read-only, pure
projection over an already-loaded ``nodes`` dict: none of them touch the
database or mutate their arguments.

Evidence note (post-0.1.117 defect fix, live plan 99340015): the
verification_target edge's producer side used to fall back to "every
target_file owner" when no owner carried operation "create_file". That
fallback made a later modify_file owner of a shared file a producer edge
source pointing BACK at an earlier verifier of the same file, cycling
against the forward file_order/explicit edges that already order the
modify chain -- six 2-node cycles on that plan alone
(``execution_integrity.execution_graph_acyclic``). The fallback is removed
entirely: ``_verification_target_edges`` now emits an edge only from a
target_file owner whose ``operation`` is "create_file"; a target with no
create_file owner in-plan emits no edge (the file is treated as
pre-existing outside the plan).
"""

from __future__ import annotations

import uuid
from typing import Any

from plan_manager.domain.step import Step
from plan_manager.domain.step_objects import (
    CONSUMER_ROLES,
    PRODUCER_ROLES,
    normalize_as_object_declarations,
)
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.execution_graph_cycles import cycles_report
from plan_manager.views.step_paths import parent_path, resolve_dependency_target

Edge = tuple[uuid.UUID, uuid.UUID]


def _artifact_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the artifact path of ``step`` (mirrors verify/gate_data.artifact_path_of).

    Reimplemented locally (four lines) rather than imported from
    ``plan_manager.verify.gate_data`` so this views-layer module does not
    take on a dependency on the verify layer; both call the same
    ``parent_path`` primitive and are therefore identical in output.
    """
    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


def _explicit_edges(nodes: dict[uuid.UUID, Step]) -> set[Edge]:
    """Recompute only the declared depends_on edges (build_edges's first pass).

    Mirrors the declared-edge loop at the top of
    ``views.dependency_graph.build_edges`` verbatim so the combined edge set
    it returns can be decomposed by type without re-deriving same-file
    priority or cross-branch inference (that logic stays exclusively inside
    build_edges/derive_cross_branch_edges; only their trusted resolution
    primitive, ``resolve_dependency_target``, is reused here).
    """
    edges: set[Edge] = set()
    for dependent_uuid, dependent in nodes.items():
        for dep_ref in dependent.depends_on:
            target = resolve_dependency_target(nodes, dependent, dep_ref)
            if target is None:
                raise ValueError(
                    f"step {dependent.step_id} depends_on unresolved target {dep_ref}"
                )
            edges.add((target.uuid, dependent_uuid))
    return edges


def _object_roles(
    nodes: dict[uuid.UUID, Step],
) -> dict[str, dict[str, Any]]:
    """In-memory analogue of views.objects.object_inventory's role accumulation.

    build_execution_graph takes only an already-loaded ``nodes`` dict (no
    database connection), so the DB-query-based object_inventory cannot be
    called directly; this recomputes just the producers/consumers/roles
    slice of that same accumulation, over ``nodes`` instead of a fresh
    SELECT, using the identical role vocabulary and normalization helper
    (domain.step_objects) object_inventory itself uses.
    """
    accum: dict[str, dict[str, Any]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        artifact_path = _artifact_path(nodes, step)
        declarations, _problems = normalize_as_object_declarations(
            step.fields or {}, allow_legacy_strings=True
        )
        for declaration in declarations:
            role = declaration.get("role")
            if role is None:
                continue
            name = declaration["name"]
            bucket = accum.setdefault(
                name, {"producers": set(), "consumers": set(), "roles": {}}
            )
            bucket["roles"][artifact_path] = role
            if role in PRODUCER_ROLES:
                bucket["producers"].add(artifact_path)
            if role in CONSUMER_ROLES:
                bucket["consumers"].add(artifact_path)
    return accum


def _object_producer_edges(
    nodes: dict[uuid.UUID, Step],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build INFERRED object_producer edges plus missing/ambiguous findings."""
    roles = _object_roles(nodes)
    raw_edges: list[dict[str, Any]] = []
    missing_producers: list[dict[str, Any]] = []
    ambiguous_dependencies: list[dict[str, Any]] = []

    for name in sorted(roles):
        bucket = roles[name]
        producers = sorted(bucket["producers"])
        consumers = sorted(bucket["consumers"])
        role_of = bucket["roles"]

        if not producers and consumers:
            missing_producers.append({"object": name, "consumers": consumers})
        if len(producers) > 1:
            ambiguous_dependencies.append({"object": name, "producers": producers})

        for producer_path in producers:
            for consumer_path in consumers:
                if producer_path == consumer_path:
                    continue
                raw_edges.append(
                    {
                        "from": producer_path,
                        "to": consumer_path,
                        "type": "object_producer",
                        "provenance": "inferred",
                        "evidence": {
                            "object": name,
                            "producer_role": role_of[producer_path],
                            "consumer_role": role_of[consumer_path],
                        },
                    }
                )
    return raw_edges, missing_producers, ambiguous_dependencies


def _verification_target_edges(nodes: dict[uuid.UUID, Step]) -> list[dict[str, Any]]:
    """Build INFERRED verification_target edges.

    An AS's ``verification`` field, when a dict with a non-empty ``target``
    string, is compared (exact match after trimming) against every other
    AS's ``target_file``. The producer side is EXCLUSIVELY the target_file
    owner(s) whose ``operation`` is "create_file" -- file creation is the
    hard prerequisite a verifier's edge encodes; a chain of later
    ``modify_file`` owners of the same file is already ordered relative to
    each other by ``file_order`` edges (views.dependency_graph.build_edges's
    same-file priority pass), so folding them in here as producers as well
    is both redundant and unsafe: a later modify_file owner would gain a
    verification_target edge pointing BACK at an earlier verifier of the
    same file, cycling against the forward file_order/explicit edges that
    already order the modify chain (CR-7 live evidence, plan 99340015: six
    2-node cycles of exactly this shape). When no owner of the target_file
    carries "create_file" in this plan, NO edge is emitted at all -- the
    file is treated as pre-existing outside the plan, which is exactly what
    ``check_no_orphan_verification`` (suppressed pending EIG block F) exists
    to flag separately. There is no all-owners fallback.
    """
    creators_by_file: dict[str, list[uuid.UUID]] = {}
    for node_uuid, step in nodes.items():
        if step.level != 5:
            continue
        if step.fields.get("operation") != "create_file":
            continue
        target_file = step.fields.get("target_file")
        if isinstance(target_file, str) and target_file.strip():
            creators_by_file.setdefault(target_file.strip(), []).append(node_uuid)

    raw_edges: list[dict[str, Any]] = []
    for verifier_uuid, verifier in nodes.items():
        if verifier.level != 5:
            continue
        verification = verifier.fields.get("verification")
        if not isinstance(verification, dict):
            continue
        target = verification.get("target")
        if not isinstance(target, str) or not target.strip():
            continue
        target = target.strip()
        creator_uuids = creators_by_file.get(target)
        if not creator_uuids:
            continue
        verifier_path = _artifact_path(nodes, verifier)
        for producer_uuid in creator_uuids:
            if producer_uuid == verifier_uuid:
                continue
            raw_edges.append(
                {
                    "from": _artifact_path(nodes, nodes[producer_uuid]),
                    "to": verifier_path,
                    "type": "verification_target",
                    "provenance": "inferred",
                    "evidence": {"target": target},
                }
            )
    return raw_edges


def _dedupe_and_sort(raw_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse edges sharing (from, to, type), keep the canonically first evidence.

    "Canonically first" means: among the raw edge dicts sharing one (from,
    to, type) key, the one whose evidence serializes (json.dumps with
    sort_keys=True) to the lexicographically smallest string. This makes the
    pick independent of insertion order, so two builds over the same input
    are byte-identical regardless of internal dict/set iteration order.
    """
    import json

    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    best_key: dict[tuple[str, str, str], str] = {}
    for edge in raw_edges:
        key = (edge["from"], edge["to"], edge["type"])
        serialized = json.dumps(edge["evidence"], sort_keys=True)
        if key not in best or serialized < best_key[key]:
            best[key] = edge
            best_key[key] = serialized
    return sorted(best.values(), key=lambda e: (e["from"], e["to"], e["type"]))


def build_execution_graph(nodes: dict[uuid.UUID, Step]) -> dict[str, Any]:
    """Build the extended execution graph (EIG block B) over ``nodes``.

    ``nodes`` is the same full-plan node set ``views.dependency_graph.
    load_steps`` returns. Composes declared/derived dependency edges
    (decomposed by type, not re-derived, from ``build_edges``) with two
    inferred edge families read off block-A object roles and AS
    verification/target_file pairs.

    Returns:
        A dict with keys:
            "explicit_edges": canonically sorted list of edge dicts with
                type in {"explicit", "file_order"}, provenance "explicit".
            "inferred_edges": canonically sorted list of edge dicts with
                type in {"object_producer", "verification_target"},
                provenance "inferred".
            "missing_producers": list of {"object", "consumers"}, one per
                object consumed by some AS but produced by none, sorted by
                "object".
            "ambiguous_dependencies": list of {"object", "producers"}, one
                per object with more than one distinct producer AS, sorted
                by "object".
            "cycles": list of ordered artifact-path lists, one per cycle
                found in the combined edge set, canonically sorted.

    Raises:
        SameFileOrderAmbiguousError: propagated from build_edges when two
            same-file writers have no deterministic cross-branch order.
        ValueError: propagated from build_edges/resolve_dependency_target
            when a declared depends_on reference cannot be resolved.
    """
    combined_uuid_edges = build_edges(nodes)
    explicit_uuid_edges = _explicit_edges(nodes)
    file_order_uuid_edges = combined_uuid_edges - explicit_uuid_edges

    raw_explicit: list[dict[str, Any]] = []
    for prereq_uuid, dependent_uuid in explicit_uuid_edges:
        raw_explicit.append(
            {
                "from": _artifact_path(nodes, nodes[prereq_uuid]),
                "to": _artifact_path(nodes, nodes[dependent_uuid]),
                "type": "explicit",
                "provenance": "explicit",
                "evidence": {},
            }
        )
    for prereq_uuid, dependent_uuid in file_order_uuid_edges:
        raw_explicit.append(
            {
                "from": _artifact_path(nodes, nodes[prereq_uuid]),
                "to": _artifact_path(nodes, nodes[dependent_uuid]),
                "type": "file_order",
                "provenance": "explicit",
                "evidence": {},
            }
        )

    object_raw_edges, missing_producers, ambiguous_dependencies = _object_producer_edges(nodes)
    verification_raw_edges = _verification_target_edges(nodes)
    raw_inferred = object_raw_edges + verification_raw_edges

    explicit_edges = _dedupe_and_sort(raw_explicit)
    inferred_edges = _dedupe_and_sort(raw_inferred)

    path_to_uuid = {_artifact_path(nodes, step): node_uuid for node_uuid, step in nodes.items()}
    inferred_uuid_edges: set[Edge] = {
        (path_to_uuid[edge["from"]], path_to_uuid[edge["to"]]) for edge in inferred_edges
    }
    cycles = cycles_report(nodes, combined_uuid_edges | inferred_uuid_edges)

    return {
        "explicit_edges": explicit_edges,
        "inferred_edges": inferred_edges,
        "missing_producers": missing_producers,
        "ambiguous_dependencies": ambiguous_dependencies,
        "cycles": cycles,
    }
