"""Deterministic and embedding-based branch estimators for SemanticIndex (C-013).

Implements the normative estimator formulas of NormativeAlgorithmSet (C-036)
consumed by plan_manager.scoring.index.score_branch. Read-only on plan data:
every function here returns computed values to its caller and stores nothing.
"""

from __future__ import annotations

import math

from plan_manager.views.branch import Branch


def load_concept_rows(conn, plan_uuid) -> list[tuple[str, str, list[str]]]:
    """Load all concepts of a plan ordered by concept_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT concept_id, definition, source_labels FROM concept "
            "WHERE plan_uuid = %s ORDER BY concept_id",
            (plan_uuid,),
        )
        return [(row[0], row[1], list(row[2])) for row in cur.fetchall()]


def concepts_from_hrs_slice(branch: Branch, concept_rows) -> set[str]:
    """Compute legacy required concept_ids from the branch's HRS slice labels."""
    slice_labels = {p.label for p in branch.hrs_slice if p.label is not None}
    required: set[str] = set()
    for concept_id, _definition, source_labels in concept_rows:
        stripped = {label[1:-1] for label in source_labels}
        if stripped & slice_labels:
            required.add(concept_id)
    return required


def branch_scope_concepts(branch: Branch) -> tuple[set[str], str]:
    """Return the branch's declared responsibility scope and its source."""
    as_scope = set(branch.atomic.concepts)
    if as_scope:
        return as_scope, "as_or_ts_declared_scope"

    ts_scope = set(branch.ts.concepts)
    if ts_scope:
        return ts_scope, "as_or_ts_declared_scope"

    gs_scope = set(branch.gs.concepts)
    if gs_scope:
        return gs_scope, "gs_declared_scope"

    return set(), "legacy_gs_source_labels"


def required_concepts(branch: Branch, concept_rows) -> set[str]:
    """Compute scope-aware concept_ids required by the branch.

    Branch scoring is responsibility-scoped: concepts explicitly declared
    by AS, then TS, then GS define the required scope. Legacy HRS label
    expansion remains only as a fallback for old or incomplete plans that
    declare no scope at any branch level.
    """
    scoped, _source = branch_scope_concepts(branch)
    if scoped:
        return scoped
    return concepts_from_hrs_slice(branch, concept_rows)


def declared_concepts(branch: Branch) -> set[str]:
    """Compute the concept_ids declared by the branch."""
    return (
        set(branch.gs.concepts)
        | set(branch.ts.concepts)
        | set(branch.atomic.concepts)
    )


def coverage_estimator(required: set[str], declared: set[str]) -> float:
    """Deterministic concept-coverage estimator."""
    if not required:
        return 1.0
    return len(required & declared) / len(required)


def coverage_diagnostics(
    branch: Branch, concept_rows, required: set[str], declared: set[str]
) -> dict:
    """Build the verbose diagnostic block for deterministic coverage."""
    _scoped, scope_source = branch_scope_concepts(branch)
    source_labels_used = sorted(
        p.label for p in branch.hrs_slice if p.label is not None
    )

    covered = required & declared
    if required:
        formula = f"{len(covered)} / {len(required)}"
    else:
        formula = "1.0 (no required concepts)"

    return {
        "required_concepts": sorted(required),
        "declared_concepts": sorted(declared),
        "missing_concepts": sorted(required - declared),
        "extra_declared_concepts": sorted(declared - required),
        "source_labels_used": source_labels_used,
        "scope_source": scope_source,
        "formula": formula,
    }


def reference_estimator(conn, branch: Branch, concept_rows) -> float:
    """Deterministic reference-resolution estimator."""
    allowed_relation_types = {
        "uses",
        "owns",
        "implements",
        "extends",
        "depends_on",
        "produces",
        "consumes",
    }
    concept_ids = {row[0] for row in concept_rows}
    total = 0
    resolved = 0

    for step in (branch.gs, branch.ts, branch.atomic):
        for concept_id in step.concepts:
            total += 1
            if concept_id in concept_ids:
                resolved += 1
        for dep_step_id in step.depends_on:
            total += 1
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM step WHERE plan_uuid = %s AND level = %s "
                    "AND parent_step_uuid IS NOT DISTINCT FROM %s "
                    "AND step_id = %s",
                    (branch.plan_uuid, step.level, step.parent_step_uuid, dep_step_id),
                )
                if cur.fetchone() is not None:
                    resolved += 1

    for relation in branch.gs.fields.get("relations", []):
        total += 1
        if not isinstance(relation, dict):
            continue
        from_concept = relation.get("from_concept")
        to_concept = relation.get("to_concept")
        relation_type = relation.get("type")
        if (
            from_concept in concept_ids
            and to_concept in concept_ids
            and relation_type in allowed_relation_types
        ):
            resolved += 1

    for source_label in branch.gs.fields.get("source_labels", []):
        total += 1
        bare_label = source_label[1:-1]
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM paragraph WHERE plan_uuid = %s AND label = %s",
                (branch.plan_uuid, bare_label),
            )
            if cur.fetchone() is not None:
                resolved += 1

    if total == 0:
        return 1.0
    return resolved / total


def branch_text(branch: Branch) -> str:
    """Concatenate the branch's descriptive text into one string."""
    return "\n\n".join(
        [
            branch.gs.fields.get("description", ""),
            branch.ts.fields.get("description", ""),
            branch.atomic.fields.get("prompt", ""),
        ]
    )


def embedding_estimator(
    branch: Branch,
    concept_rows,
    required: set[str],
    concept_weight: float,
    vectors: dict[str, list[float]],
) -> float:
    """Embedding-cosine estimator computed in the concept basis.

    Consumes a precomputed ``vectors`` map from text to embedding vector
    (branch text and every concept definition), so it performs no network
    call: all vectorization happens once, up front, as a single batch.
    """

    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    v = vectors[branch_text(branch)]

    c_required: list[float] = []
    c_actual: list[float] = []
    for concept_id, definition, _source_labels in concept_rows:
        e_i = vectors[definition]
        c_required.append(concept_weight if concept_id in required else 0.0)
        c_actual.append(max(0.0, _cosine(v, e_i)))

    if not any(c_required) or not any(c_actual):
        return 0.0
    return max(0.0, _cosine(c_required, c_actual))
