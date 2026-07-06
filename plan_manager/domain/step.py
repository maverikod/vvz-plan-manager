"""Domain model for the Step entity (C-005): the single stored entity for plan
levels 3-5 (global step, tactical step, atomic step), with declarative
per-level identifier patterns and validation rules.
"""


import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID


LEVEL_PREFIXES: dict[int, str] = {3: "G", 4: "T", 5: "A"}


STEP_ID_PATTERNS: dict[int, re.Pattern[str]] = {
    3: re.compile(r"^G-\d{3}$"),
    4: re.compile(r"^T-\d{3}$"),
    5: re.compile(r"^A-\d{3}$"),
}


SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


CONCEPT_ID_PATTERN: re.Pattern[str] = re.compile(r"^C-\d{3}$")


class StepValidationError(ValueError):
    """Raised when a Step instance fails one or more validate_step checks.

    The exception message lists every failed check found during
    validation, joined by "; ".
    """


@dataclass
class Step:
    """Unified stored entity for plan levels 3, 4, and 5 (C-005).

    Attributes:
        uuid: Immutable primary identity of this step.
        plan_uuid: Identity of the plan this step belongs to.
        parent_step_uuid: Identity of the parent step that defines this
            step's id-uniqueness scope, or None when this step is a
            level-3 step (whose scope is the plan itself).
        level: Plan hierarchy level of this step; one of 3, 4, 5.
        step_id: Human-readable identifier matching the pattern for
            `level` in STEP_ID_PATTERNS (e.g. "G-001", "T-002", "A-003").
        slug: Kebab-case short name matching SLUG_PATTERN.
        fields: Level-specific required fields, as a plain dict.
        depends_on: step_id values of sibling steps this step depends on;
            each entry matches the same pattern as `step_id`.
        concepts: MRS concept_id values referenced by this step; each
            entry matches CONCEPT_ID_PATTERN (e.g. "C-005").
        project_id: Optional analysis-server project UUID text bound to
            this step, or None for plan-level work.
        status: Lifecycle status string (e.g. "draft").
    """

    uuid: UUID
    plan_uuid: UUID
    parent_step_uuid: UUID | None
    level: int
    step_id: str
    slug: str
    fields: dict[str, Any]
    depends_on: list[str]
    concepts: list[str]
    project_id: str | None
    status: str


def validate_step(step: Step) -> None:
    """Validate a Step instance against the Step entity rules (C-005).

    Checks, all of which must pass:
        1. step.level is one of 3, 4, 5.
        2. step.step_id matches STEP_ID_PATTERNS[step.level] (only
           checked when check 1 passes; skipped otherwise).
        3. step.slug matches SLUG_PATTERN.
        4. Every entry of step.depends_on matches
           STEP_ID_PATTERNS[step.level] (only checked when check 1
           passes; skipped otherwise).
        5. Every entry of step.concepts matches CONCEPT_ID_PATTERN.
        6. step.status is a non-empty string.

    Args:
        step: The Step instance to validate.

    Returns:
        None when all checks pass.

    Raises:
        StepValidationError: When one or more checks fail. The
            exception message is every failed check's description
            joined by "; ".
    """
    errors: list[str] = []

    if step.level not in LEVEL_PREFIXES:
        errors.append(
            f"level must be one of {sorted(LEVEL_PREFIXES)}, got {step.level!r}"
        )
    else:
        pattern = STEP_ID_PATTERNS[step.level]
        if not pattern.match(step.step_id):
            errors.append(
                f"step_id {step.step_id!r} does not match pattern for level {step.level}"
            )
        for dep in step.depends_on:
            if not pattern.match(dep):
                errors.append(
                    f"depends_on entry {dep!r} does not match pattern for level {step.level}"
                )

    if not SLUG_PATTERN.match(step.slug):
        errors.append(f"slug {step.slug!r} does not match SLUG_PATTERN")

    for concept_id in step.concepts:
        if not CONCEPT_ID_PATTERN.match(concept_id):
            errors.append(
                f"concepts entry {concept_id!r} does not match CONCEPT_ID_PATTERN"
            )

    if not step.status:
        errors.append("status must be a non-empty string")

    if errors:
        raise StepValidationError("; ".join(errors))


def next_free_step_id(existing_step_ids: list[str], level: int) -> str:
    """Compute the next free zero-padded step_id within one parent scope.

    Implements the pure part of the normative next-free-id algorithm:
    given the step_id values already present in one parent scope (same
    plan_uuid, same parent_step_uuid, same level), find the highest
    numeric part among entries matching the level's identifier pattern
    and return the next value, zero-padded to three digits with the
    level's prefix. Locking and database access are the caller's
    responsibility; this function is pure.

    Args:
        existing_step_ids: step_id values already present in the parent
            scope. Entries that do not match STEP_ID_PATTERNS[level] are
            ignored.
        level: Plan hierarchy level; one of 3, 4, 5. Selects the prefix
            via LEVEL_PREFIXES and the pattern via STEP_ID_PATTERNS.

    Returns:
        The next free step_id: prefix + "-" + zero-padded three-digit
        number. "<prefix>-001" when existing_step_ids contains no entry
        matching the level's pattern.

    Raises:
        KeyError: When level is not a key of LEVEL_PREFIXES.
    """
    prefix = LEVEL_PREFIXES[level]
    pattern = STEP_ID_PATTERNS[level]
    max_n = 0
    for step_id in existing_step_ids:
        if pattern.match(step_id):
            n = int(step_id.split("-", 1)[1])
            if n > max_n:
                max_n = n
    return f"{prefix}-{max_n + 1:03d}"
