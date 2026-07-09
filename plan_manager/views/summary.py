"""Deterministic summarization strategy for plan nodes (SummarizationStrategy, C-011).

Produces the structured summary fields later consumed when constructing per-node
semantic summaries for atomic steps and reconstructed summaries for tactical steps,
global steps, and the plan. The minimal deterministic implementation in this module
derives every field directly from the supplied node data without invoking a language
model. build_structured_summary exposes strategy as a parameter so a model-based
structured-summarization implementation can be substituted later without changing
callers.
"""

from __future__ import annotations

from typing import Callable

StructuredSummaryFields = dict[str, object]
SummarizationStrategy = Callable[[dict[str, object]], StructuredSummaryFields]

_STRUCTURED_FIELD_KEYS = (
    "entities",
    "operations",
    "contracts",
    "inputs",
    "outputs",
    "invariants",
    "diagnostics",
    "risks",
    "target_files",
    "source_concepts",
    "source_labels",
    "children_used",
    "summary_text",
)


def deterministic_summary_strategy(node_fields: dict[str, object]) -> StructuredSummaryFields:
    """Derive structured summary fields from node_fields without a language model.

    node_fields carries the own-fields payload of the node being summarized: for
    an atomic step, its name, prompt, verification, target_file, operation,
    concepts, dependencies, and parent_tactical_step_context; for a tactical
    step, global step, or the plan, its own description, inputs, outputs,
    source_labels, and child_summaries (the already-produced summaries of its
    children).

    Returns a dict with exactly the keys entities, operations, contracts,
    inputs, outputs, invariants, diagnostics, risks, target_files,
    source_concepts, source_labels, children_used, and summary_text.
    """
    concepts = list(node_fields.get("concepts") or [])
    verification = node_fields.get("verification")
    target_file = node_fields.get("target_file")
    operation = node_fields.get("operation")

    text_parts: list[str] = []
    for key in ("name", "description", "prompt"):
        value = node_fields.get(key)
        if value:
            text_parts.append(str(value))

    return {
        "entities": sorted(set(concepts)),
        "operations": [operation] if operation else [],
        "contracts": [verification] if verification else [],
        "inputs": list(node_fields.get("inputs") or []),
        "outputs": list(node_fields.get("outputs") or []),
        "invariants": [],
        "diagnostics": [],
        "risks": [],
        "target_files": [target_file] if target_file else [],
        "source_concepts": sorted(set(concepts)),
        "source_labels": list(node_fields.get("source_labels") or []),
        "children_used": list(node_fields.get("child_summaries") or []),
        "summary_text": " ".join(text_parts),
    }


def build_structured_summary(
    node_fields: dict[str, object],
    strategy: SummarizationStrategy = deterministic_summary_strategy,
) -> StructuredSummaryFields:
    """Produce structured_summary_fields for node_fields via strategy.

    strategy defaults to deterministic_summary_strategy. Passing a different
    callable substitutes a model-based structured-summarization implementation
    without changing callers. The returned dict always has exactly the keys
    listed in deterministic_summary_strategy's docstring.
    """
    return strategy(node_fields)
