"""Per-node scope-aware text and concept-set helpers for ScopedNode assembly
(plan_manager.scoring.reproduction_input), reused across the atomic, tactical,
global, and plan levels of SemanticReproductionTree (C-001) construction.

Builds the ExpectedScope (C-005) text of a node from the scope-aware
coverage foundation (ScopeAwareCoverageFoundation, C-002) exposed by
plan_manager.scoring.estimators and plan_manager.views.expected_scope.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import psycopg

from plan_manager.hrs.paragraphs import list_paragraphs
from plan_manager.scoring.estimators import (
    coverage_diagnostics,
    declared_concepts,
    required_concepts,
)
from plan_manager.views.branch import Branch
from plan_manager.views.expected_scope import build_expected_scope


AGGREGATED_SCOPE_SOURCE = "aggregated_child_scope"


def paragraph_text_by_label(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> dict[str, str]:
    """Map every plan HRS paragraph's bare label to its text.

    Built from plan_manager.hrs.paragraphs.list_paragraphs(conn, plan_uuid),
    which returns one dict per stored paragraph with keys "label"
    (str | None), "binding", "position", "text". Paragraphs whose "label" is
    None are omitted from the returned mapping.
    """
    return {
        paragraph["label"]: paragraph["text"]
        for paragraph in list_paragraphs(conn, plan_uuid)
        if paragraph["label"] is not None
    }


def expected_scope_text(expected_scope: dict[str, object]) -> str:
    """Render an ExpectedScope (C-005) dict as one plain-text string.

    expected_scope is the dict returned by
    plan_manager.views.expected_scope.build_expected_scope: keys
    scope_source, concepts (dict of concept_id to a dict with keys
    definition, properties, source_labels), relations (list of
    (from_concept, to_concept, relation_type) tuples), hrs_paragraphs (dict
    of bare label to paragraph text).

    Builds three text sections, each joined internally by "\\n" and the
    sections joined by "\\n\\n"; a section that would be empty contributes
    nothing:
      1. For each concept_id in expected_scope["concepts"] sorted ascending:
         one line "{concept_id}: {definition}" followed by one line
         "- {prop}" per entry of that concept's "properties" list, in list
         order.
      2. For each (from_concept, to_concept, relation_type) tuple in
         expected_scope["relations"] sorted ascending (tuple order): one
         line "{from_concept} {relation_type} {to_concept}".
      3. For each label in expected_scope["hrs_paragraphs"] sorted
         ascending: that label's paragraph text.
    """
    sections: list[str] = []

    concepts = cast(
        "dict[str, dict[str, Any]]", expected_scope.get("concepts") or {}
    )
    concept_lines: list[str] = []
    for concept_id in sorted(concepts):
        entry = concepts[concept_id]
        concept_lines.append(f"{concept_id}: {entry['definition']}")
        for prop in entry.get("properties", []):
            concept_lines.append(f"- {prop}")
    if concept_lines:
        sections.append("\n".join(concept_lines))

    relations = cast(
        "list[tuple[str, str, str]]", expected_scope.get("relations") or []
    )
    relation_lines = [
        f"{from_concept} {relation_type} {to_concept}"
        for from_concept, to_concept, relation_type in sorted(relations)
    ]
    if relation_lines:
        sections.append("\n".join(relation_lines))

    hrs_paragraphs = cast(
        "dict[str, str]", expected_scope.get("hrs_paragraphs") or {}
    )
    paragraph_lines = [hrs_paragraphs[label] for label in sorted(hrs_paragraphs)]
    if paragraph_lines:
        sections.append("\n".join(paragraph_lines))

    return "\n\n".join(sections)


def leaf_scope(
    branch: Branch, concept_rows: list[tuple[str, str, list[str]]]
) -> tuple[set[str], set[str], dict[str, object]]:
    """Resolve one atomic branch's scope-aware concept sets and diagnostic.

    Returns (required, declared, coverage): required is
    plan_manager.scoring.estimators.required_concepts(branch, concept_rows);
    declared is plan_manager.scoring.estimators.declared_concepts(branch);
    coverage is plan_manager.scoring.estimators.coverage_diagnostics(branch,
    concept_rows, required, declared), the dict-of-lists diagnostic consumed
    as the scope mapping for build_expected_scope.
    """
    required = required_concepts(branch, concept_rows)
    declared = declared_concepts(branch)
    coverage = coverage_diagnostics(branch, concept_rows, required, declared)
    return required, declared, coverage


def aggregated_scope(required: set[str]) -> dict[str, object]:
    """Build the scope mapping for a non-leaf node's ExpectedScope.

    Returns {"required_concepts": sorted(required), "scope_source":
    AGGREGATED_SCOPE_SOURCE}, the scope mapping consumed by
    plan_manager.views.expected_scope.build_expected_scope for a tactical,
    global, or plan-level node whose required_concepts is the union of its
    children's required_concepts rather than a single branch's own scope.
    """
    return {"required_concepts": sorted(required), "scope_source": AGGREGATED_SCOPE_SOURCE}
