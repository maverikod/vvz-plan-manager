"""Regression (F3 root cause): a node's own embedding text is never empty.

The deterministic summarizer yields an empty summary_text for the PLAN root
(it has no own prose, only children). The embedding service returns no results
for an empty string, so the root degraded with "embed-client response missing
results". The SRT input layer now falls back an empty own_text to the join of
the children's own texts (or the node path for a childless node).
"""

from plan_manager.scoring.reproduction_input import _embedding_own_text
from plan_manager.scoring.reproduction_tree import ScopedNode


def _leaf(path: str, own_text: str) -> ScopedNode:
    return ScopedNode(
        path=path,
        own_text=own_text,
        expected_text="expected",
        required_concepts=set(),
        declared_concepts=set(),
        children=[],
    )


def test_non_empty_summary_is_returned_unchanged() -> None:
    children = [_leaf("G-001", "child text")]
    assert _embedding_own_text("PLAN", "real plan summary", children) == "real plan summary"


def test_empty_summary_falls_back_to_children_join() -> None:
    children = [_leaf("G-001", "first global"), _leaf("G-002", "second global")]
    assert _embedding_own_text("PLAN", "", children) == "first global\n\nsecond global"


def test_whitespace_only_summary_falls_back() -> None:
    children = [_leaf("G-001", "only child")]
    assert _embedding_own_text("PLAN", "   \n  ", children) == "only child"


def test_empty_children_are_skipped_in_join() -> None:
    children = [_leaf("G-001", ""), _leaf("G-002", "kept"), _leaf("G-003", "  ")]
    assert _embedding_own_text("PLAN", "", children) == "kept"


def test_childless_empty_node_falls_back_to_path() -> None:
    assert _embedding_own_text("G-001/T-001/A-001", "", []) == "G-001/T-001/A-001"
    # A node whose children are all empty also has no join material.
    assert _embedding_own_text("PLAN", "", [_leaf("G-001", "")]) == "PLAN"
