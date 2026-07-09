"""Regression tests for BUG: branch_dump used the stale immutable step.slug.

dump_prompts must name its snapshot files after a display slug derived from
the step's CURRENT fields.name (which step_update can change), falling back
to the stored immutable slug only when no usable name exists.
"""

import re

from plan_manager.domain.step import SLUG_PATTERN
from plan_manager.views.prompt_assembly import display_slug


def test_display_slug_follows_semantic_rename() -> None:
    # Creation-time slug says one thing; the step was renamed via step_update.
    assert (
        display_slug("Wire mechanism and delegation documentation sections", "wire-mechanism-documentation-section")
        == "wire-mechanism-and-delegation-documentation-sections"
    )


def test_display_slug_normalizes_case_punctuation_and_spaces() -> None:
    assert display_slug("Node coefficient computation", "x") == "node-coefficient-computation"
    assert display_slug("Plan-to-ScopedNode assembly & tree computation!", "x") == (
        "plan-to-scopednode-assembly-tree-computation"
    )
    assert display_slug("  spaced   out  ", "x") == "spaced-out"


def test_display_slug_falls_back_when_name_unusable() -> None:
    assert display_slug(None, "stored-slug") == "stored-slug"
    assert display_slug("", "stored-slug") == "stored-slug"
    assert display_slug("!!! ---", "stored-slug") == "stored-slug"
    assert display_slug(42, "stored-slug") == "stored-slug"


def test_display_slug_output_matches_step_slug_pattern() -> None:
    samples = [
        "Node coefficient computation",
        "Plan-to-ScopedNode assembly & tree computation!",
        "A1 b2 C3",
        "unicode Ünïcode name",
    ]
    for name in samples:
        slug = display_slug(name, "fallback")
        assert re.fullmatch(SLUG_PATTERN, slug), (name, slug)


def test_dump_prompts_uses_display_slug_in_paths() -> None:
    # Static regression: the path-building source must go through display_slug
    # and select the current fields name, not the raw stored slug alone.
    import inspect

    from plan_manager.views import prompt_assembly

    source = inspect.getsource(prompt_assembly.dump_prompts)
    assert "display_slug(" in source
    assert "fields->>'name'" in source
