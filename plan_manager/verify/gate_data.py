"""Read-only tree loader and scoping helpers for the mechanical gate (C-012)."""

import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.step import Step
from plan_manager.views.branch import BranchScope
from plan_manager.views.dependency_graph import impact_set, parent_path


@dataclass
class GateTree:
    steps: dict[uuid.UUID, Step]
    concept_ids: list[str]
    relations: list[tuple[str, str, str]]
    labels: list[str]
    counts: dict[str, int]


def artifact_path_of(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    """Return the artifact path of ``step`` within ``nodes``."""
    if step.level == 3:
        return step.step_id
    prefix = parent_path(nodes, step)
    return f"{prefix}/{step.step_id}"


def load_tree(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> GateTree:
    """Load the full read-only tree for ``plan_uuid`` needed by the mechanical gate."""
    steps: dict[uuid.UUID, Step] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug, "
            "fields, depends_on, concepts, project_id, status FROM step WHERE plan_uuid = %s",
            (plan_uuid,),
        )
        for row in cur.fetchall():
            (
                s_uuid,
                s_plan_uuid,
                s_parent_step_uuid,
                s_level,
                s_step_id,
                s_slug,
                s_fields,
                s_depends_on,
                s_concepts,
                s_project_id,
                s_status,
            ) = row
            steps[s_uuid] = Step(
                uuid=s_uuid,
                plan_uuid=s_plan_uuid,
                parent_step_uuid=s_parent_step_uuid,
                level=s_level,
                step_id=s_step_id,
                slug=s_slug,
                fields=s_fields or {},
                depends_on=list(s_depends_on) if s_depends_on else [],
                concepts=list(s_concepts) if s_concepts else [],
                project_id=s_project_id,
                status=s_status,
            )

        cur.execute("SELECT concept_id FROM concept WHERE plan_uuid = %s", (plan_uuid,))
        concept_ids = [row[0] for row in cur.fetchall()]

        cur.execute(
            "SELECT from_concept, to_concept, type FROM relation WHERE plan_uuid = %s",
            (plan_uuid,),
        )
        relations = [(row[0], row[1], row[2]) for row in cur.fetchall()]

        cur.execute(
            "SELECT label FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE ORDER BY position",
            (plan_uuid,),
        )
        labels = [row[0] for row in cur.fetchall()]

        cur.execute(
            "SELECT count(*) FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE",
            (plan_uuid,),
        )
        paragraph_count = cur.fetchone()[0]

    counts = {
        "steps": len(steps),
        "concepts": len(concept_ids),
        "paragraphs": paragraph_count,
    }
    return GateTree(
        steps=steps,
        concept_ids=concept_ids,
        relations=relations,
        labels=labels,
        counts=counts,
    )


def scope_steps(tree: GateTree, branch: BranchScope | None) -> list[Step]:
    """Return all checked steps for plan scope or one hierarchical branch
    scope (bug e197b94a): depth "gs" checks the whole GS subtree (the GS
    plus every TS and AS descendant), depth "ts" checks the TS subtree
    (the GS, that TS, and every AS descendant of it), and depth "as"
    checks exactly the three-step atomic branch path (unchanged from the
    pre-fix single-triple behavior). A branch with zero AS descendants at
    depth "gs" or "ts" is valid input: the descendant list is simply
    shorter, never an error.
    """
    if branch is None:
        return sorted(
            tree.steps.values(),
            key=lambda step: (step.level, _safe_artifact_path(tree.steps, step)),
        )
    if branch.depth == "as":
        assert branch.ts is not None and branch.atomic is not None
        return [branch.gs, branch.ts, branch.atomic]
    if branch.depth == "ts":
        assert branch.ts is not None
        descendants = [tree.steps[node_uuid] for node_uuid in impact_set(tree.steps, branch.ts.uuid)]
        return [branch.gs, branch.ts, *descendants]
    descendants = [tree.steps[node_uuid] for node_uuid in impact_set(tree.steps, branch.gs.uuid)]
    return [branch.gs, *descendants]


def _safe_artifact_path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    try:
        return artifact_path_of(nodes, step)
    except ValueError:
        return step.step_id
