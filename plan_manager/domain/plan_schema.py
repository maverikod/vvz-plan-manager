"""Declarative configuration object describing identifier patterns,
per-level required fields, and exchange-layout naming (C-006 PlanSchema)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PlanSchema:
    """Declarative configuration object describing identifier patterns,
    per-level required fields, and exchange-layout naming for a
    development plan.

    Attributes:
        identifier_patterns: Mapping from plan level (int) to the
            identifier pattern string for that level, e.g.
            {2: "C-NNN", 3: "G-NNN", 4: "T-NNN", 5: "A-NNN"}, where NNN
            denotes three zero-padded digits.
        required_fields: Mapping from plan level (int) to the list of
            required field names for artifacts at that level.
        exchange_layout: Mapping from exchange layout element name (str)
            to its naming convention (str), describing the file layout
            used for import/export of a plan.
    """

    identifier_patterns: dict[int, str]
    required_fields: dict[int, list[str]]
    exchange_layout: dict[str, str]


def default_plan_schema() -> PlanSchema:
    """Return the default PlanSchema matching the planning standard.

    Returns:
        PlanSchema: a new PlanSchema instance populated with the standard
        default identifier patterns, per-level required fields, and
        exchange layout naming, exactly as follows.
    """
    return PlanSchema(
        identifier_patterns={
            2: "C-NNN",
            3: "G-NNN",
            4: "T-NNN",
            5: "A-NNN",
        },
        required_fields={
            3: [
                "step_id",
                "name",
                "description",
                "concepts",
                "relations",
                "source_labels",
                "depends_on",
                "tactical_steps",
                "status",
            ],
            4: [
                "step_id",
                "parent_global_step",
                "name",
                "description",
                "concepts",
                "inputs",
                "outputs",
                "atomic_steps",
                "status",
            ],
            5: [
                "step_id",
                "parent_tactical_step",
                "name",
                "target_file",
                "operation",
                "priority",
                "depends_on",
                "concepts",
                "prompt",
                "verification",
                "status",
            ],
        },
        exchange_layout={
            "source_spec": "source_spec.md",
            "machine_spec": "spec.yaml",
            "global_step_dir": "G-NNN-<slug>",
            "tactical_step_dir": "T-NNN-<slug>",
            "step_readme": "README.yaml",
            "atomic_step_file": "atomic_steps/A-NNN-<slug>.yaml",
        },
    )


def apply_overrides(schema: PlanSchema, overrides: dict) -> PlanSchema:
    """Return a new PlanSchema with top-level fields replaced by overrides.

    Args:
        schema: The base PlanSchema to apply overrides on top of. Not
            mutated by this function.
        overrides: A dict whose keys must be a subset of
            {"identifier_patterns", "required_fields", "exchange_layout"}.
            For each key present in overrides, the corresponding value
            replaces the corresponding field of schema in full (a shallow
            replacement per top-level key, not a deep merge). Keys of
            overrides that are absent leave the corresponding field of
            schema unchanged in the returned PlanSchema.

    Returns:
        PlanSchema: a new PlanSchema instance combining schema's
        unreplaced fields with the replaced fields from overrides. The
        input schema object is not mutated.

    Raises:
        ValueError: if overrides contains any key other than
            "identifier_patterns", "required_fields", or
            "exchange_layout".
    """
    known_keys = {"identifier_patterns", "required_fields", "exchange_layout"}
    unknown_keys = set(overrides.keys()) - known_keys
    if unknown_keys:
        raise ValueError(
            f"Unknown PlanSchema override key(s): {sorted(unknown_keys)}"
        )
    return PlanSchema(
        identifier_patterns=overrides.get(
            "identifier_patterns", schema.identifier_patterns
        ),
        required_fields=overrides.get("required_fields", schema.required_fields),
        exchange_layout=overrides.get(
            "exchange_layout", schema.exchange_layout
        ),
    )
