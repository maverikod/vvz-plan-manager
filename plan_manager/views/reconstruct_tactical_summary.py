"""Reconstructed summary for a tactical step (ReconstructedSummary, C-004).

Reconstructs a tactical step's structured summary bottom-up from the tactical
step's own description, its inputs and outputs, and the sum of the SemanticSummary
(C-003) of its child atomic steps, by invoking the pluggable SummarizationStrategy
(C-011) through build_structured_summary.
"""

from __future__ import annotations

from plan_manager.views.summary import (
    StructuredSummaryFields,
    SummarizationStrategy,
    build_structured_summary,
    deterministic_summary_strategy,
)


def reconstruct_tactical_summary(
    tactical_fields: dict[str, object],
    child_atomic_summaries: list[StructuredSummaryFields],
    strategy: SummarizationStrategy = deterministic_summary_strategy,
) -> StructuredSummaryFields:
    """Reconstruct the summary of one tactical step.

    tactical_fields carries the tactical step's own description, inputs, and
    outputs. child_atomic_summaries is the list of SemanticSummary produced for
    the tactical step's child atomic steps. They are merged into one node_fields
    payload and passed to build_structured_summary, which returns the thirteen
    structured keys entities, operations, contracts, inputs, outputs, invariants,
    diagnostics, risks, target_files, source_concepts, source_labels,
    children_used, and summary_text.
    """
    node_fields: dict[str, object] = {
        "description": tactical_fields.get("description"),
        "inputs": tactical_fields.get("inputs") or [],
        "outputs": tactical_fields.get("outputs") or [],
        "child_summaries": child_atomic_summaries,
    }
    return build_structured_summary(node_fields, strategy)
