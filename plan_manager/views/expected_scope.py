"""Concept-aware expected scope for a plan node (ExpectedScope, C-005).

Builds the concept-aware slice of the HRS and MRS that a node's reconstructed or
semantic summary is compared against, restricted to the node's scope. The node's
scope is resolved by the existing ScopeAwareCoverageFoundation (C-002): its
required_concepts, declared_concepts, missing_concepts, and scope_source. The
slice carries, for each in-scope concept, its definition and properties, the
relations whose from_concept is in scope, and the HRS paragraphs reached through
the in-scope concepts' source labels.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from plan_manager.domain.concept import Concept


def build_expected_scope(
    scope: Mapping[str, object],
    concepts: Iterable[Concept],
    relations: Iterable[tuple[str, str, str]],
    paragraph_text_by_label: Mapping[str, str],
) -> dict[str, object]:
    """Build the ExpectedScope slice for a node.

    scope is the ScopeAwareCoverageFoundation result carrying required_concepts,
    declared_concepts, missing_concepts, and scope_source; its required_concepts
    (a collection of concept_id strings) defines the in-scope concept set.
    concepts is the full list of plan Concept records. relations is the full list
    of (from_concept, to_concept, relation_type) tuples. paragraph_text_by_label
    maps a bare HRS label (braces stripped, e.g. "onka") to its paragraph text.

    Returns a dict with keys scope_source, concepts, relations, and
    hrs_paragraphs. concepts maps each in-scope concept_id to a dict with keys
    definition, properties, and source_labels. relations is the list of
    (from_concept, to_concept, relation_type) tuples whose from_concept is in
    scope. hrs_paragraphs maps each in-scope bare label to its paragraph text when
    that label is present in paragraph_text_by_label.
    """
    required = set(scope.get("required_concepts") or [])

    concept_slice: dict[str, dict[str, object]] = {}
    in_scope_labels: set[str] = set()
    for concept in concepts:
        if concept.concept_id in required:
            concept_slice[concept.concept_id] = {
                "definition": concept.definition,
                "properties": list(concept.properties),
                "source_labels": list(concept.source_labels),
            }
            for label in concept.source_labels:
                in_scope_labels.add(label.strip("{}"))

    relation_slice = [
        (from_concept, to_concept, relation_type)
        for from_concept, to_concept, relation_type in relations
        if from_concept in required
    ]

    hrs_paragraphs = {
        label: paragraph_text_by_label[label]
        for label in in_scope_labels
        if label in paragraph_text_by_label
    }

    return {
        "scope_source": scope.get("scope_source"),
        "concepts": concept_slice,
        "relations": relation_slice,
        "hrs_paragraphs": hrs_paragraphs,
    }
