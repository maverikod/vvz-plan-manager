"""Reconstructed summary for the plan (ReconstructedSummary, C-004).

Reconstructs the plan's structured summary bottom-up from the sum of the
reconstructed summaries of all global steps, kept concept-aware by carrying the
deduplicated union of the global summaries' source concepts rather than one flat
text, by invoking the pluggable SummarizationStrategy (C-011) through
build_structured_summary.
"""

from __future__ import annotations

from plan_manager.views.summary import (
    StructuredSummaryFields,
    SummarizationStrategy,
    build_structured_summary,
    deterministic_summary_strategy,
)


def reconstruct_plan_summary(
    global_summaries: list[StructuredSummaryFields],
    strategy: SummarizationStrategy = deterministic_summary_strategy,
) -> StructuredSummaryFields:
    """Reconstruct the summary of the whole plan.

    global_summaries is the list of reconstructed summaries produced for every
    global step. Their source_concepts are collected into a deduplicated union so
    the plan summary stays concept-aware, and the list is passed as the plan's
    children. The resulting node_fields payload is passed to
    build_structured_summary, which returns the thirteen structured keys entities,
    operations, contracts, inputs, outputs, invariants, diagnostics, risks,
    target_files, source_concepts, source_labels, children_used, and summary_text.
    """
    concepts: list[str] = []
    for child in global_summaries:
        for concept_id in (child.get("source_concepts") or []):
            if concept_id not in concepts:
                concepts.append(concept_id)
    node_fields: dict[str, object] = {
        "concepts": concepts,
        "child_summaries": global_summaries,
    }
    return build_structured_summary(node_fields, strategy)
