"""The third plan-completion-lock seam (bug c3950b83): commands that
address their mutation target by the entity's OWN uuid rather than a
`plan` (name-or-uuid) parameter or a primary anchor.

Two seams already exist:

- plan_manager.commands.resolve.resolve_plan_guarded -- covers every
  command that resolves a `plan` parameter to a Plan and mutates through
  it directly (step_*, cascade_*, plan_unfreeze, para_*, concept_*/
  relation_*, plan_delete/import/project_*, and the runtime-write family
  that also takes `plan`).
- plan_manager.domain.primary_anchor.validate_anchor -- covers
  todo_create and the shared anchor path (comment/execution_attempt/
  review_result/escalation/bug-source anchors of anchor_type "plan" or
  "step") that resolves a plan via a raw anchor_plan_uuid.

SWEEP FINDING (bug c3950b83 follow-up, 2026-07-23): a THIRD class of
command takes a `plan` parameter that resolve_plan_guarded dutifully
checks, YET never cross-validates it against the entity actually being
mutated -- the entity is fetched and mutated purely by its OWN uuid
(bug_id, comment_uuid, escalation_uuid, impact_uuid, fix_uuid,
propagation_uuid, ...); the `plan` parameter is accepted and checked, but
a caller could pass a DIFFERENT, non-completed plan while the addressed
entity's TRUE owning plan is in fact completed, silently bypassing the
lock. A separate class of command (todo_update/resolve/close/delete/
link_*, execution_attempt_report, model_binding_update/remove,
comment_delete, runtime_link_*) never had a `plan` parameter at ALL.

Every function below derives the entity's TRUE owning plan_uuid (or None
when the entity is genuinely not plan-bound, e.g. a TODO anchored none/
project/file, or a system/role-scoped model binding) and calls the ONE
shared check, domain.plan.refuse_if_completed -- no scattered copies of
the completion-check SQL exist anywhere in this module.
"""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.plan import refuse_if_completed
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem
from plan_manager.storage.bug_report_store import get_bug
from plan_manager.storage.todo_store import get_todo


def refuse_if_bug_plan_completed(conn: psycopg.Connection, bug: BugReport) -> None:
    """Refuse when a BugReport's own source_plan_uuid anchor is completed.

    A no-op when the bug's source_anchor_type is not "plan"/"step" (
    source_plan_uuid is None in every other case).
    """
    refuse_if_completed(conn, bug.source_plan_uuid)


def refuse_if_todo_plan_completed(conn: psycopg.Connection, todo: TodoItem) -> None:
    """Refuse when a TodoItem's own anchor_plan_uuid is completed.

    A no-op for a todo anchored none/project/file (anchor_plan_uuid is
    None in every case other than anchor_type "plan"/"step").
    """
    refuse_if_completed(conn, todo.anchor_plan_uuid)


def refuse_if_comment_plan_completed(conn: psycopg.Connection, comment: RuntimeComment) -> None:
    """Refuse when a RuntimeComment's own anchor_plan_uuid is completed."""
    refuse_if_completed(conn, comment.anchor_plan_uuid)


def refuse_if_escalation_plan_completed(conn: psycopg.Connection, escalation: Escalation) -> None:
    """Refuse when an Escalation's own anchor_plan_uuid is completed."""
    refuse_if_completed(conn, escalation.anchor_plan_uuid)


def refuse_if_execution_attempt_plan_completed(conn: psycopg.Connection, attempt: ExecutionAttempt) -> None:
    """Refuse when an ExecutionAttempt's own (non-nullable) plan_uuid is completed."""
    refuse_if_completed(conn, attempt.plan_uuid)


def refuse_if_model_binding_plan_completed(conn: psycopg.Connection, binding: ModelBinding) -> None:
    """Refuse when a ModelBinding's own plan_uuid is completed.

    A no-op for a system/role-scoped binding (plan_uuid is None).
    """
    refuse_if_completed(conn, binding.plan_uuid)


def refuse_if_bug_impact_plan_completed(conn: psycopg.Connection, impact: BugImpact) -> None:
    """Refuse when a BugImpact's own target_plan_uuid is completed.

    A no-op when the impact's target_type is not "plan" (target_plan_uuid
    is None in every other case). This checks the impact's OWN target
    anchor, not its parent bug's source_plan_uuid -- the two are
    independent; call refuse_if_bug_plan_completed separately (via
    get_bug on the impact's bug_uuid) where the parent bug itself is
    also being read/touched.
    """
    refuse_if_completed(conn, impact.target_plan_uuid)


def refuse_if_bug_fix_propagation_plan_completed(conn: psycopg.Connection, propagation: BugFixPropagation) -> None:
    """Refuse when a BugFixPropagation's own linked_plan_uuid is completed."""
    refuse_if_completed(conn, propagation.linked_plan_uuid)


def refuse_if_bug_fix_plan_completed(conn: psycopg.Connection, bug_fix: BugFix) -> None:
    """Refuse when a BugFix's PARENT bug's source_plan_uuid is completed.

    BugFix carries no plan_uuid field of its own -- it references
    bug_uuid, and the two-hop derivation (bug_fix -> bug -> source_plan_uuid)
    is the only way to find its owning plan. A no-op if the parent bug
    cannot be found (should not happen given the FK, but this function
    never assumes) or is not plan-bound.
    """
    bug = get_bug(conn, bug_fix.bug_uuid)
    if bug is not None:
        refuse_if_completed(conn, bug.source_plan_uuid)


def refuse_if_link_endpoint_plan_completed(
    conn: psycopg.Connection, entity_type: str, entity_uuid: uuid.UUID
) -> None:
    """Refuse when a runtime/todo link ENDPOINT's owning plan is completed.

    entity_type is "bug" or "todo" (the only two RUNTIME_LINK_ENTITY_TYPES;
    a todo_link's endpoints are always both "todo" and may call this with
    entity_type="todo" directly). A no-op if the referenced entity cannot
    be found (a dangling reference is a different, pre-existing concern
    this function does not police) or is not plan-bound.
    """
    if entity_type == "bug":
        bug = get_bug(conn, entity_uuid)
        if bug is not None:
            refuse_if_completed(conn, bug.source_plan_uuid)
    elif entity_type == "todo":
        todo = get_todo(conn, entity_uuid)
        if todo is not None:
            refuse_if_completed(conn, todo.anchor_plan_uuid)
