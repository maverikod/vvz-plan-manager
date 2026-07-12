"""Prompt assembly visibility filtering and runtime-context composition test coverage (C-035, C-028, HRS {d118} bullets 21-22)."""

import contextlib
import types
import uuid
from unittest.mock import patch

from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.runtime.prompt_context import PromptContextNote, PromptContextLimits
from plan_manager.runtime.prompt_context_sources import filter_visible_notes
from plan_manager.runtime import prompt_context_assembly as pca
from plan_manager.domain.model_resolution import ResolutionTarget, ModelResolutionError


def _make_comment(visibility: str, body: str) -> RuntimeComment:
    return RuntimeComment(
        comment_uuid=uuid.uuid4(),
        primary_anchor_type="step",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        kind="comment",
        visibility=visibility,
        author="tester",
        body=body,
        resolved=None,
        supersedes_comment_uuid=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )


def test_filter_visible_notes_excludes_audit_only_from_execution_context() -> None:
    audit_comment = _make_comment("audit_only", "internal audit note")
    execution_comment = _make_comment("execution_context", "relevant execution note")

    result = filter_visible_notes([audit_comment, execution_comment], "execution")

    result_bodies = [note.body for note in result]
    assert "internal audit note" not in result_bodies
    assert "relevant execution note" in result_bodies


def test_filter_visible_notes_public_summary_reaches_execution_context() -> None:
    public_comment = _make_comment("public_summary", "public note")
    owner_comment = _make_comment("owner_context", "owner-only note")
    reviewer_comment = _make_comment("reviewer_context", "reviewer-only note")

    result = filter_visible_notes([public_comment, owner_comment, reviewer_comment], "execution")

    result_bodies = [note.body for note in result]
    assert "public note" in result_bodies
    assert "owner-only note" not in result_bodies
    assert "reviewer-only note" not in result_bodies


def test_filter_visible_notes_owner_context_kind() -> None:
    comments = [
        _make_comment("audit_only", "audit"),
        _make_comment("execution_context", "execution"),
        _make_comment("owner_context", "owner"),
        _make_comment("reviewer_context", "reviewer"),
        _make_comment("public_summary", "public"),
    ]

    result = filter_visible_notes(comments, "owner")

    result_bodies = [note.body for note in result]
    assert result_bodies == ["owner", "public"]


def test_filter_visible_notes_maps_fields_and_preserves_order() -> None:
    first = _make_comment("execution_context", "first note")
    second = _make_comment("public_summary", "second note")

    result = filter_visible_notes([first, second], "execution")

    assert len(result) == 2
    assert isinstance(result[0], PromptContextNote)
    assert result[0].comment_uuid == first.comment_uuid
    assert result[0].kind == first.kind
    assert result[0].visibility == first.visibility
    assert result[0].body == "first note"
    assert result[1].comment_uuid == second.comment_uuid
    assert result[1].body == "second note"


def test_filter_visible_notes_empty_input_returns_empty_list() -> None:
    assert filter_visible_notes([], "execution") == []


def _identity(value):
    return value


def _fake_todo(*, status, anchor_step_uuid=None, anchor_plan_uuid=None):
    return types.SimpleNamespace(
        status=status, anchor_step_uuid=anchor_step_uuid, anchor_plan_uuid=anchor_plan_uuid
    )


def _fake_bug(*, status):
    return types.SimpleNamespace(status=status)


def _fake_attempt(*, status="failed"):
    return types.SimpleNamespace(status=status, attempt_uuid=uuid.uuid4())


def _fake_escalation(*, anchor_step_uuid=None):
    return types.SimpleNamespace(anchor_step_uuid=anchor_step_uuid)


def _assemble(
    *,
    plan_uuid,
    step_uuid,
    todos=(),
    bugs=(),
    comments=(),
    failed_attempts=(),
    all_attempts=(),
    reviews=(),
    escalations=(),
    binding_resolves=True,
    limits=None,
    context_kind="execution",
    step_path=None,
):
    def fake_list_todos(conn, **kwargs):
        return list(todos)

    def fake_list_bugs(conn, **kwargs):
        return list(bugs)

    def fake_list_comments(conn, **kwargs):
        return list(comments)

    def fake_list_execution_attempts(conn, **kwargs):
        if kwargs.get("status") == "failed":
            return list(failed_attempts)
        return list(all_attempts)

    def fake_list_review_results(conn, **kwargs):
        return list(reviews)

    def fake_list_escalations(conn, **kwargs):
        return list(escalations)

    def fake_list_bindings_for_resolution(conn, **kwargs):
        return []

    def fake_resolve(candidates, target):
        if not binding_resolves:
            raise ModelResolutionError("no binding applies")
        return types.SimpleNamespace()

    resolution_target = ResolutionTarget(role="executor", plan_uuid=plan_uuid, step_uuid=step_uuid)
    effective_limits = limits if limits is not None else PromptContextLimits()

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(pca, "list_todos", fake_list_todos))
        stack.enter_context(patch.object(pca, "list_bugs", fake_list_bugs))
        stack.enter_context(patch.object(pca, "list_comments", fake_list_comments))
        stack.enter_context(patch.object(pca, "list_execution_attempts", fake_list_execution_attempts))
        stack.enter_context(patch.object(pca, "list_review_results", fake_list_review_results))
        stack.enter_context(patch.object(pca, "list_escalations", fake_list_escalations))
        stack.enter_context(
            patch.object(pca, "list_bindings_for_resolution", fake_list_bindings_for_resolution)
        )
        stack.enter_context(patch.object(pca, "resolve_effective_binding", fake_resolve))
        stack.enter_context(patch.object(pca, "to_context_todo", _identity))
        stack.enter_context(patch.object(pca, "to_context_bug", _identity))
        stack.enter_context(patch.object(pca, "to_context_attempt", _identity))
        stack.enter_context(patch.object(pca, "to_context_review", _identity))
        stack.enter_context(patch.object(pca, "to_context_binding", _identity))
        stack.enter_context(patch.object(pca, "to_context_escalation", _identity))
        return pca.assemble_runtime_prompt_context(
            None,
            plan_uuid=plan_uuid,
            step_uuid=step_uuid,
            step_path=step_path,
            context_kind=context_kind,
            resolution_target=resolution_target,
            limits=effective_limits,
        )


def test_assemble_runtime_prompt_context_happy_path_composes_sections() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    todos = [
        _fake_todo(status="open", anchor_step_uuid=step_uuid),
        _fake_todo(status="in_progress", anchor_plan_uuid=plan_uuid),
    ]
    bugs = [_fake_bug(status="confirmed")]
    comments = [_make_comment("execution_context", "a relevant note")]
    attempt = _fake_attempt(status="needs_review")
    context = _assemble(
        plan_uuid=plan_uuid,
        step_uuid=step_uuid,
        todos=todos,
        bugs=bugs,
        comments=comments,
        failed_attempts=[_fake_attempt(status="failed")],
        all_attempts=[attempt],
        reviews=[types.SimpleNamespace()],
        escalations=[_fake_escalation(anchor_step_uuid=step_uuid)],
        binding_resolves=True,
    )

    assert len(context.todos) == 2
    assert len(context.blocker_bugs) == 1
    assert [note.body for note in context.notes] == ["a relevant note"]
    assert len(context.failed_attempts) == 1
    assert len(context.review_findings) == 1
    assert len(context.escalations) == 1
    assert context.model_binding is not None
    assert context.truncated is False
    assert context.target_plan_uuid == plan_uuid
    assert context.target_step_uuid == step_uuid


def test_assemble_runtime_prompt_context_excludes_audit_only_notes() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    comments = [
        _make_comment("audit_only", "internal audit note"),
        _make_comment("execution_context", "relevant execution note"),
    ]
    context = _assemble(
        plan_uuid=plan_uuid,
        step_uuid=step_uuid,
        comments=comments,
        context_kind="execution",
    )

    bodies = [note.body for note in context.notes]
    assert "internal audit note" not in bodies
    assert "relevant execution note" in bodies


def test_assemble_runtime_prompt_context_truncates_over_limit_sections() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    todos = [_fake_todo(status="open", anchor_step_uuid=step_uuid) for _ in range(3)]
    context = _assemble(
        plan_uuid=plan_uuid,
        step_uuid=step_uuid,
        todos=todos,
        limits=PromptContextLimits(max_todos=2),
    )

    assert len(context.todos) == 2
    assert context.truncated is True


def test_assemble_runtime_prompt_context_model_binding_none_on_resolution_error() -> None:
    plan_uuid = uuid.uuid4()
    step_uuid = uuid.uuid4()
    context = _assemble(
        plan_uuid=plan_uuid,
        step_uuid=step_uuid,
        binding_resolves=False,
    )

    assert context.model_binding is None
