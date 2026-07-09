"""Regression tests for BUG: branch_dump used the stale immutable step.slug.

dump_prompts must name its snapshot files after a display slug derived from
the step's CURRENT fields.name (which step_update can change), falling back
to the stored immutable slug only when no usable name exists.
"""

import json
import re
import uuid

from plan_manager.domain.step import SLUG_PATTERN, Step
from plan_manager.views.prompt_assembly import display_slug, step_content


def _step(slug: str, name: object) -> Step:
    """Build an atomic step whose stored slug and current name may diverge."""
    fields: dict[str, object] = {"operation": "create_file", "prompt": ""}
    if name is not None:
        fields["name"] = name
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=uuid.uuid4(),
        parent_step_uuid=uuid.uuid4(),
        level=5,
        step_id="A-004",
        slug=slug,
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status="frozen",
    )


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


def test_step_content_slug_follows_semantic_rename() -> None:
    # BUG-BRANCH-DUMP-STALE-SLUG-IN-CONTENT: the prompt/dump CONTENT (not just
    # the file name) must carry the name-derived display slug, never the stale
    # immutable stored slug, when the step was renamed via step_update.
    step = _step(
        slug="create-watcher-entrypoint",
        name="Create vector worker entrypoint for container runtime",
    )
    content = json.loads(step_content(step))
    assert content["slug"] == "create-vector-worker-entrypoint-for-container-runtime"
    assert "create-watcher-entrypoint" not in step_content(step)


def test_step_content_slug_falls_back_to_stored_slug() -> None:
    # With no usable fields.name, the content slug is the stored slug (no
    # empty or degraded slug, and no crash on a missing name field).
    assert json.loads(step_content(_step("stored-slug", None)))["slug"] == "stored-slug"
    assert json.loads(step_content(_step("stored-slug", "")))["slug"] == "stored-slug"
    assert json.loads(step_content(_step("stored-slug", "!!! ---")))["slug"] == "stored-slug"


def test_step_content_slug_matches_step_slug_pattern() -> None:
    step = _step("fallback", "Plan-to-ScopedNode assembly & tree computation!")
    slug = json.loads(step_content(step))["slug"]
    assert re.fullmatch(SLUG_PATTERN, slug)
