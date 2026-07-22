"""Regression tests for bug 5ebe3ce5 (wrong_output, major).

parse.atomic_single_code_file (AS_MULTIPLE_CODE_FILES) used to treat every
path-like token on a write-intent-bearing SENTENCE as an additional write
target, with no regard for negation or read-only reference intent: "Do not
modify foo/old.py" or "reuse conventions from foo/old.py without changing
it" were both flagged as commanding a second write, purely because their
sentence also contained (or, in the second case, was merged by the old
whole-segment split with a sentence that contained) a write-intent verb.

The fix reworks _additional_write_target_hits/_additional_write_targets in
plan_manager.verify.gate_structure to classify write intent CLAUSE-by-clause
(splitting on sentence boundaries, newlines, commas, and contrastive
conjunctions -- not just sentences) and to void a clause's write verdict
whenever it carries a negation cue (English or Russian) or an explicit
read-only/reference-only framing marker, while a genuinely commanded second
write in its own clause is still flagged.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_structure import (
    WriteTargetHit,
    _additional_write_target_hits,
    _additional_write_targets,
    check_parse_atomic_single_code_file,
)

PLAN = uuid.uuid4()


def _atomic_step(target: str, prompt: str, *, step_id: str = "A-001") -> Step:
    """Build a minimal level-5 (AS) Step with the given target_file/prompt."""
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN,
        parent_step_uuid=uuid.uuid4(),
        level=5,
        step_id=step_id,
        slug=step_id.lower(),
        fields={
            "name": step_id,
            "target_file": target,
            "operation": "modify_file",
            "priority": 1,
            "prompt": prompt,
            "verification": "pytest tests/test_x.py",
        },
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree(steps: list[Step]) -> GateTree:
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


# ---------------------------------------------------------------------------
# The bug's two real-world examples.
# ---------------------------------------------------------------------------


def test_bug_example_do_not_modify_is_not_a_write_target() -> None:
    """"Do not modify foo/old.py" must not be treated as a second write."""
    step = _atomic_step(
        "plan_manager/foo/new.py",
        "Update plan_manager/foo/new.py to add the new helper. "
        "Do not modify plan_manager/foo/old.py.",
    )
    assert _additional_write_targets(step, "plan_manager/foo/new.py") == {}


def test_bug_example_reuse_conventions_without_changing_is_not_a_write_target() -> None:
    """"reuse conventions from X without changing it" must not flag X."""
    step = _atomic_step(
        "plan_manager/foo/new.py",
        "Update plan_manager/foo/new.py, reusing conventions from "
        "plan_manager/foo/old.py without changing it.",
    )
    assert _additional_write_targets(step, "plan_manager/foo/new.py") == {}


def test_bug_example_combined_negation_and_reuse_in_one_prompt() -> None:
    """The full combined prompt from the bug report (both clauses) is clean."""
    step = _atomic_step(
        "plan_manager/foo/new.py",
        "Update plan_manager/foo/new.py to add the new helper. "
        "Do not modify plan_manager/foo/old.py; reuse conventions from "
        "plan_manager/foo/old.py without changing it.",
    )
    assert _additional_write_targets(step, "plan_manager/foo/new.py") == {}


# ---------------------------------------------------------------------------
# Negation variants: English and Russian, pre-verb and "without/без" forms.
# ---------------------------------------------------------------------------


def test_english_do_not_negation_variants() -> None:
    for phrase in (
        "Do not modify src/legacy.py.",
        "Don't modify src/legacy.py.",
        "Never modify src/legacy.py.",
        "You must not modify src/legacy.py.",
        "You should not modify src/legacy.py.",
        "You cannot modify src/legacy.py.",
    ):
        step = _atomic_step("src/main.py", f"Update src/main.py. {phrase}")
        assert _additional_write_targets(step, "src/main.py") == {}, phrase


def test_without_gerund_negation_form() -> None:
    step = _atomic_step(
        "src/main.py",
        "Update src/main.py without touching src/legacy.py.",
    )
    assert _additional_write_targets(step, "src/main.py") == {}


def test_russian_negation_forms() -> None:
    for phrase in (
        "Не удаляй src/legacy.py.",
        "Нельзя удалять src/legacy.py.",
        "Никогда не изменяй src/legacy.py.",
    ):
        step = _atomic_step("src/main.py", f"Обнови src/main.py. {phrase}")
        assert _additional_write_targets(step, "src/main.py") == {}, phrase


# ---------------------------------------------------------------------------
# Read-only / reference framing without an explicit negation word.
# ---------------------------------------------------------------------------


def test_read_only_reference_framing_variants() -> None:
    for phrase in (
        "Use src/legacy.py as a reference.",
        "Use src/legacy.py as a pattern.",
        "See src/legacy.py for comparison.",
        "Read src/legacy.py for context.",
        "src/legacy.py remains unchanged.",
    ):
        step = _atomic_step("src/main.py", f"Update src/main.py. {phrase}")
        assert _additional_write_targets(step, "src/main.py") == {}, phrase


def test_noun_collision_with_write_verb_is_suppressed_by_read_only_framing() -> None:
    """"Patch" as a noun ("patch history") must not itself trigger a write
    verdict when the clause is explicitly framed as read-only reference."""
    step = _atomic_step(
        "src/main.py",
        "Patch history for src/legacy.py is available as a reference; "
        "update src/main.py accordingly.",
    )
    assert _additional_write_targets(step, "src/main.py") == {}


# ---------------------------------------------------------------------------
# Mixed clauses in one sentence (comma / contrastive conjunction splitting).
# ---------------------------------------------------------------------------


def test_mixed_update_a_comma_dont_touch_b() -> None:
    step = _atomic_step(
        "src/main.py",
        "Update src/main.py, don't touch src/other.py.",
    )
    assert _additional_write_targets(step, "src/main.py") == {}


def test_sentence_level_update_a_dot_do_not_modify_b_keeps_a_drops_b() -> None:
    """"Update A. Do not modify B." must keep A (a genuine second write)
    and drop B."""
    step = _atomic_step(
        "src/main.py",
        "Update src/helper.py as required. Do not modify src/legacy.py.",
    )
    assert _additional_write_targets(step, "src/main.py") == {"prompt": ["src/helper.py"]}


# ---------------------------------------------------------------------------
# True-positive guards: the checker's detection power must survive the fix.
# ---------------------------------------------------------------------------


def test_plain_second_write_is_still_flagged() -> None:
    step = _atomic_step(
        "src/main.py",
        "Modify src/main.py and edit src/other.py. Read src/context.py for context.",
    )
    assert _additional_write_targets(step, "src/main.py") == {"prompt": ["src/other.py"]}


def test_also_update_second_file_is_still_flagged() -> None:
    step = _atomic_step("src/main.py", "Also update src/other.py.")
    assert _additional_write_targets(step, "src/main.py") == {"prompt": ["src/other.py"]}


def test_do_not_modify_b_but_do_update_c_keeps_c_drops_b() -> None:
    """"do not modify B but DO update C" must keep C and drop B."""
    step = _atomic_step(
        "src/main.py",
        "Do not modify src/legacy.py but DO update src/other.py.",
    )
    assert _additional_write_targets(step, "src/main.py") == {"prompt": ["src/other.py"]}


# ---------------------------------------------------------------------------
# check_parse_atomic_single_code_file: finding still fires for a genuine
# second write, keeps its stable message prefix, and now carries per-path
# source spans + inferred intent.
# ---------------------------------------------------------------------------


def test_check_still_flags_genuine_second_write_with_spans() -> None:
    step = _atomic_step("src/main.py", "Update src/main.py. Also update src/other.py.")
    findings = check_parse_atomic_single_code_file(_tree([step]), [step])
    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "parse.atomic_single_code_file"
    assert "AS_MULTIPLE_CODE_FILES:" in finding.message
    assert "target_file='src/main.py'" in finding.message
    assert "additional_write_targets=['src/other.py']" in finding.message
    assert "source_fields=['prompt']" in finding.message
    assert "spans=" in finding.message
    assert "'path': 'src/other.py'" in finding.message
    assert "'intent': 'commanded_write'" in finding.message
    assert "'field': 'prompt'" in finding.message


def test_check_does_not_flag_negated_reference() -> None:
    step = _atomic_step(
        "src/main.py",
        "Update src/main.py. Do not modify src/legacy.py.",
    )
    findings = check_parse_atomic_single_code_file(_tree([step]), [step])
    assert findings == []


def test_additional_write_target_hits_carries_clause_span() -> None:
    step = _atomic_step("src/main.py", "Also update src/other.py for the fix.")
    hits = _additional_write_target_hits(step, "src/main.py")
    assert hits == [
        WriteTargetHit(
            field_name="prompt",
            path="src/other.py",
            clause="Also update src/other.py for the fix.",
        )
    ]
