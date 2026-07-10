"""Semantic reproduction mechanism documentation for the info command (C-012)."""

from typing import Any


def semantic_reproduction_mechanism_reference() -> dict[str, Any]:
    """Return the technical documentation of the semantic reproduction mechanism.

    Documents concept C-001 (SemanticReproductionTree) and concept C-012
    (SelfDocumentedTechnology): the mechanism's own MRS definition and
    properties, its bottom-up reconstruction direction across the plan
    hierarchy, its refactoring constraint relative to existing scoring
    commands, its diagnostic-tree result shape, its declared MRS relations
    as bare structural references, and the meaning and intent of the
    self-documented information surface that exposes this content.
    """
    return {
        "purpose": (
            "Carry the full technical documentation of the semantic "
            "reproduction mechanism and the meaning of the technology, "
            "not only a glossary or field summaries, so an executor can "
            "rely on a single reference (C-012)."
        ),
        "concept": {
            "concept_id": "C-001",
            "name": "SemanticReproductionTree",
            "definition": (
                "A plan tree annotated at every node with semantic "
                "coefficients, produced by refactoring the existing "
                "scoring so the sum of child steps reproduces the "
                "meaning of parent levels bottom-up."
            ),
            "properties": [
                "Evaluates the whole global/tactical/atomic tree, not a single branch.",
                "Solves the inverse problem: atomic steps reproduce their tactical step, "
                "tactical steps their global step, and global steps the plan area.",
                "Built as a refactoring of the existing plan_score/scoring code without "
                "breaking plan_score, branch_weak, or plan_validate.",
                "Its result is a diagnostic tree carrying coefficients at every node, "
                "suitable to hand to an agent.",
            ],
        },
        "reconstruction_direction": {
            "atomic_to_tactical": (
                "The meaning of a tactical step is reconstructed from the sum of its "
                "atomic steps."
            ),
            "tactical_to_global": (
                "The meaning of a global step is reconstructed from the sum of its "
                "tactical steps."
            ),
            "global_to_plan": (
                "The meaning of the plan's HRS/MRS area is reconstructed from the sum "
                "of its global steps."
            ),
        },
        "refactoring_constraint": (
            "The mechanism is built as a refactoring of the existing plan_score/scoring "
            "code, not as a new standalone project; the existing plan_score, "
            "branch_weak, and plan_validate commands must not be broken."
        ),
        "result_shape": (
            "The result is not a flat score but the plan tree with coefficients at "
            "every node, suitable to hand to an agent as a diagnostic tree."
        ),
        "declared_relations": [
            {"relation_type": "uses", "to_concept": "C-002"},
            {"relation_type": "produces", "to_concept": "C-006"},
            {"relation_type": "owns", "to_concept": "C-010"},
        ],
        "technology_intent": {
            "concept_id": "C-012",
            "name": "SelfDocumentedTechnology",
            "definition": (
                "The planner's information surface that exposes the full technical "
                "documentation of the semantic reproduction mechanism and the meaning "
                "of the technology, not only a glossary."
            ),
            "properties": [
                "Carries the algorithms for building the structured summaries, "
                "computing the per-node coefficients, and assembling and diffing the "
                "snapshots.",
                "Documents the meaning and intent of the technology, not only field "
                "summaries or a glossary.",
                "Lets an executor rely on a single reference.",
            ],
        },
    }
