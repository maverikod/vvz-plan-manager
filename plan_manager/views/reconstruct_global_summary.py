"""Reconstructed summary for a global step (ReconstructedSummary, C-004).

Reconstructs a global step's structured summary bottom-up from the global step's
own description, its relations and source labels, and the sum of the reconstructed
summaries of its child tactical steps, by invoking the pluggable
SummarizationStrategy (C-011) through build_structured_summary.
"""

from __future__ import annotations

from plan_manager.views.summary import (
    StructuredSummaryFields,
    SummarizationStrategy,
    build_structured_summary,
    deterministic_summary_strategy,
)


def reconstruct_global_summary(
    global_fields: dict[str, object],
    child_tactical_summaries: list[StructuredSummaryFields],
    strategy: SummarizationStrategy = deterministic_summary_strategy,
) -> StructuredSummaryFields:
    """Reconstruct the summary of one global step.

    global_fields carries the global step's own description, relations, and
    source_labels. child_tactical_summaries is the list of reconstructed summaries
    produced for the global step's child tactical steps. They are merged into one
    node_fields payload and passed to build_structured_summary, which returns the
    thirteen structured keys entities, operations, contracts, inputs, outputs,
    invariants, diagnostics, risks, target_files, source_concepts, source_labels,
    children_used, and summary_text.
    """
    node_fields: dict[str, object] = {
        "description": global_fields.get("description"),
        "relations": global_fields.get("relations") or [],
        "source_labels": global_fields.get("source_labels") or [],
        "child_summaries": child_tactical_summaries,
    }
    return build_structured_summary(node_fields, strategy)
