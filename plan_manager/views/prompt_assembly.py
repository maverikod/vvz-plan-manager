"""Deterministic prompt assembly for atomic steps (C-011), per the normative
assembly algorithm (C-036).
"""

import os
import re
import uuid
from dataclasses import dataclass

import psycopg

from plan_manager.domain.plan import get_plan
from plan_manager.domain.step import Step
from plan_manager.storage.canonical import canonical_json
from plan_manager.views.branch import Branch, resolve_branch


class PromptAssemblyError(ValueError):
    """Raised when a declared concept_id has no matching concept row in the plan."""


def token_estimate(text: str) -> int:
    """Deterministic character-based estimate of the token count of text.

    Computed as (len(text) + 3) // 4, per the normative token estimate algorithm.

    Args:
        text: The text to estimate.

    Returns:
        The estimated token count.
    """
    return (len(text) + 3) // 4


def _canonical_json_text(value: object) -> str:
    """Return canonical JSON as UTF-8 text for prompt rendering."""
    return canonical_json(value).decode("utf-8")


def step_content(step: Step) -> str:
    """Canonical JSON content of one step, used as a fixed part of prompt assembly.

    Args:
        step: The step to serialize.

    Returns:
        Canonical JSON text of a dict with keys step_id, slug, level, depends_on,
        concepts, status, fields (in that order), taken from the step's
        matching attributes.
    """
    return _canonical_json_text(
        {
            "step_id": step.step_id,
            "slug": step.slug,
            "level": step.level,
            "depends_on": step.depends_on,
            "concepts": step.concepts,
            "project_id": step.project_id,
            "status": step.status,
            "fields": step.fields,
        }
    )


def plan_project_context(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> str:
    """Render plan-level project bindings for prompt context."""
    plan = get_plan(conn, plan_uuid)
    return _canonical_json_text(
        {
            "project_ids": plan.project_ids,
            "primary_project_id": plan.primary_project_id,
        }
    )


def current_step_project_context(step: Step) -> str:
    """Render current step project binding for prompt context."""
    if step.project_id is None:
        return _canonical_json_text({"project_id": None, "scope": "plan-level"})
    return _canonical_json_text({"project_id": step.project_id})


def mrs_excerpt(conn: psycopg.Connection, plan_uuid: uuid.UUID, concept_ids: list[str]) -> str:
    """Part 1 (MRS excerpt) body of a prompt: concept and relation lines for concept_ids.

    For each id in concept_ids sorted ascending, looks up the concept row of the
    plan by concept_id and appends one canonical JSON text line with keys concept_id,
    name, definition, properties, source_labels (properties and source_labels as
    lists). If a concept_id has no row, raises PromptAssemblyError naming the
    missing concept_id. After all concept lines, looks up every relation of the
    plan whose from_concept and to_concept are both in concept_ids, sorted by
    (from_concept, to_concept, type), and appends one canonical JSON text line per
    relation with keys from_concept, to_concept, type. All lines are joined with
    the newline character.

    Args:
        conn: Open database connection.
        plan_uuid: UUID of the plan.
        concept_ids: The declared concept ids to excerpt.

    Returns:
        The part 1 body text.

    Raises:
        PromptAssemblyError: If a concept_id in concept_ids has no concept row
            in the plan.
    """
    sorted_ids = sorted(concept_ids)
    lines: list[str] = []
    with conn.cursor() as cur:
        for concept_id in sorted_ids:
            cur.execute(
                "SELECT name, definition, properties, source_labels FROM concept "
                "WHERE plan_uuid = %s AND concept_id = %s",
                (plan_uuid, concept_id),
            )
            row = cur.fetchone()
            if row is None:
                raise PromptAssemblyError(
                    f"concept_id {concept_id} declared but has no concept row in plan {plan_uuid}"
                )
            name, definition, properties, source_labels = row
            lines.append(
                _canonical_json_text(
                    {
                        "concept_id": concept_id,
                        "name": name,
                        "definition": definition,
                        "properties": list(properties),
                        "source_labels": list(source_labels),
                    }
                )
            )
        cur.execute(
            "SELECT from_concept, to_concept, type FROM relation "
            "WHERE plan_uuid = %s AND from_concept = ANY(%s) AND to_concept = ANY(%s) "
            "ORDER BY from_concept, to_concept, type",
            (plan_uuid, sorted_ids, sorted_ids),
        )
        for from_concept, to_concept, rel_type in cur.fetchall():
            lines.append(
                _canonical_json_text(
                    {
                        "from_concept": from_concept,
                        "to_concept": to_concept,
                        "type": rel_type,
                    }
                )
            )
    return "\n".join(lines)


def assemble_prompt(conn: psycopg.Connection, branch: Branch) -> str:
    """Assemble the full deterministic prompt for one atomic step branch.

    Builds the five parts in fixed order: (1) "# MRS excerpt" with the body from
    mrs_excerpt(conn, branch.plan_uuid, branch.atomic.concepts); (2) "# HRS slice"
    with body the paragraphs of branch.hrs_slice in list order, each rendered as
    "{" + paragraph.label + "} " + paragraph.text, joined pairwise with two
    newline characters; (3) "# Global step" with body step_content(branch.gs);
    (4) "# Tactical step" with body step_content(branch.ts); (5) "# Atomic step
    delta" with body step_content(branch.atomic). Each part is rendered as its
    header line followed by one newline character and its body. The five
    rendered parts are joined pairwise with two newline characters.

    Args:
        conn: Open database connection.
        branch: The resolved branch to assemble a prompt for.

    Returns:
        The full assembled prompt text.
    """
    parts = [
        ("# Plan project bindings", plan_project_context(conn, branch.plan_uuid)),
        ("# Current step project", current_step_project_context(branch.atomic)),
        ("# MRS excerpt", mrs_excerpt(conn, branch.plan_uuid, branch.atomic.concepts)),
        (
            "# HRS slice",
            "\n\n".join(
                "{" + paragraph.label + "} " + paragraph.text
                for paragraph in branch.hrs_slice
            ),
        ),
        ("# Global step", step_content(branch.gs)),
        ("# Tactical step", step_content(branch.ts)),
        ("# Atomic step delta", step_content(branch.atomic)),
    ]
    return "\n\n".join(header + "\n" + body for header, body in parts)


@dataclass
class TokenReport:
    """Token estimate report for one assembled prompt against a plan's context budget.

    Attributes:
        estimate: The token estimate of the prompt text.
        budget: The plan's context budget in tokens.
        exceeds: True if estimate is strictly greater than budget.
    """

    estimate: int
    budget: int
    exceeds: bool


def check_budget(conn: psycopg.Connection, plan_uuid: uuid.UUID, prompt_text: str) -> TokenReport:
    """Compute the token estimate report for prompt_text against the plan's context budget.

    Args:
        conn: Open database connection.
        plan_uuid: UUID of the plan.
        prompt_text: The assembled prompt text to estimate.

    Returns:
        A TokenReport with estimate = token_estimate(prompt_text), budget =
        get_plan(conn, plan_uuid).context_budget, and exceeds = estimate > budget.
    """
    budget = get_plan(conn, plan_uuid).context_budget
    estimate = token_estimate(prompt_text)
    return TokenReport(estimate=estimate, budget=budget, exceeds=estimate > budget)


_DISPLAY_SLUG_RE = re.compile(r"[^a-z0-9]+")


def display_slug(name: object, fallback: str) -> str:
    """Derive a fresh filename slug from a step's current fields.name.

    The stored step.slug is immutable after creation, while fields.name may be
    changed by step_update; a filename derived from the stored slug can
    therefore contradict the step's current semantic name. This helper
    lowercases name, replaces every run of characters outside [a-z0-9] with a
    single hyphen, and strips leading/trailing hyphens, yielding a value that
    matches the step slug pattern. When name is not a non-empty string or
    nothing remains after normalization, fallback (the stored slug) is
    returned, so a dump filename never degrades to an empty slug.

    Args:
        name: The step's current fields.name value (any type; only a
            non-empty str produces a derived slug).
        fallback: The stored immutable step.slug to use when name yields
            no usable slug.

    Returns:
        The derived display slug, or fallback.
    """
    if not isinstance(name, str):
        return fallback
    slug = _DISPLAY_SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or fallback


def dump_prompts(conn: psycopg.Connection, plan_uuid: uuid.UUID, dump_dir: str) -> list[str]:
    """Write every atomic step's assembled prompt of the plan to files under dump_dir.

    Enumerates all level-5 (atomic) steps of the plan by selecting, for each
    atomic step, its parent tactical step and that tactical step's parent global
    step, ordered ascending by (global step step_id, tactical step step_id,
    atomic step step_id). For each row, resolves the branch with
    resolve_branch(conn, plan_uuid, gs_step_id, ts_step_id, as_step_id), assembles
    its prompt with assemble_prompt(conn, branch), and writes the prompt text to
    the file path os.path.join(dump_dir, f"{gs_step_id}-{gs_display_slug}",
    f"{ts_step_id}-{ts_display_slug}", f"{as_step_id}-{as_display_slug}.txt"),
    creating parent directories with os.makedirs(target_dir, exist_ok=True)
    before writing. Each display slug is derived from the step's CURRENT
    fields.name via display_slug (falling back to the stored immutable slug),
    so dump filenames follow semantic renames performed through step_update
    instead of echoing the stale creation-time slug. The prompt files are
    written and never read back.

    Args:
        conn: Open database connection.
        plan_uuid: UUID of the plan.
        dump_dir: Root directory to write the snapshot under.

    Returns:
        The sorted list of file paths written.
    """
    written: list[str] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT gs.step_id, gs.slug, gs.fields->>'name', "
            "ts.step_id, ts.slug, ts.fields->>'name', "
            "as_.step_id, as_.slug, as_.fields->>'name' "
            "FROM step as_ "
            "JOIN step ts ON as_.parent_step_uuid = ts.uuid "
            "JOIN step gs ON ts.parent_step_uuid = gs.uuid "
            "WHERE as_.plan_uuid = %s AND as_.level = 5 "
            "ORDER BY gs.step_id, ts.step_id, as_.step_id",
            (plan_uuid,),
        )
        rows = cur.fetchall()
    for (
        gs_step_id,
        gs_slug,
        gs_name,
        ts_step_id,
        ts_slug,
        ts_name,
        as_step_id,
        as_slug,
        as_name,
    ) in rows:
        branch = resolve_branch(conn, plan_uuid, gs_step_id, ts_step_id, as_step_id)
        prompt_text = assemble_prompt(conn, branch)
        target_dir = os.path.join(
            dump_dir,
            f"{gs_step_id}-{display_slug(gs_name, gs_slug)}",
            f"{ts_step_id}-{display_slug(ts_name, ts_slug)}",
        )
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(
            target_dir, f"{as_step_id}-{display_slug(as_name, as_slug)}.txt"
        )
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(prompt_text)
        written.append(target_path)
    return sorted(written)
