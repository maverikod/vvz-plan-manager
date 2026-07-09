"""Atomic-step semantic summary builder (SemanticSummary, C-003).

Builds the structured SemanticSummary for an atomic step from the atomic step's
own name, prompt, verification, target file, operation, concepts, and
dependencies together with the context of the parent tactical step, by invoking
the pluggable SummarizationStrategy (C-011) through build_structured_summary.
"""

from __future__ import annotations

from plan_manager.views.summary import (
    StructuredSummaryFields,
    SummarizationStrategy,
    build_structured_summary,
    deterministic_summary_strategy,
)


def build_atomic_semantic_summary(
    atomic_fields: dict[str, object],
    parent_tactical_context: dict[str, object],
    strategy: SummarizationStrategy = deterministic_summary_strategy,
) -> StructuredSummaryFields:
    """Build the SemanticSummary for one atomic step.

    atomic_fields carries the atomic step's own name, prompt, verification,
    target_file, operation, concepts, and dependencies. parent_tactical_context
    carries the parent tactical step's context. Both are merged into one
    node_fields payload and passed to build_structured_summary, which returns the
    thirteen structured keys entities, operations, contracts, inputs, outputs,
    invariants, diagnostics, risks, target_files, source_concepts, source_labels,
    children_used, and summary_text.
    """
    node_fields: dict[str, object] = {
        "name": atomic_fields.get("name"),
        "prompt": atomic_fields.get("prompt"),
        "verification": atomic_fields.get("verification"),
        "target_file": atomic_fields.get("target_file"),
        "operation": atomic_fields.get("operation"),
        "concepts": atomic_fields.get("concepts") or [],
        "dependencies": atomic_fields.get("dependencies") or [],
        "parent_tactical_context": parent_tactical_context,
    }
    return build_structured_summary(node_fields, strategy)
