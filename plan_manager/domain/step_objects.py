"""Canonical validation and normalization helpers for level-5 object declarations."""

from __future__ import annotations

from typing import Any, Mapping

from plan_manager.domain.step import CONCEPT_ID_PATTERN


def normalize_as_object_declarations(
    fields: Mapping[str, Any],
    *,
    allow_legacy_strings: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize a level-5 step's ``fields.objects`` declarations."""
    value = fields.get("objects")
    if value is None:
        return [], []

    normalized: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    if not isinstance(value, list):
        return (
            [],
            [
                {
                    "field_name": "objects",
                    "index": None,
                    "message": "objects must be a list",
                }
            ],
        )

    for index, item in enumerate(value):
        if isinstance(item, str):
            if allow_legacy_strings and item.strip():
                normalized.append({"name": item, "concepts": []})
                continue
            problems.append(
                {
                    "field_name": "objects",
                    "index": index,
                    "message": f"objects[{index}] must be an object",
                }
            )
            continue
        if not isinstance(item, dict):
            problems.append(
                {
                    "field_name": "objects",
                    "index": index,
                    "message": f"objects[{index}] must be an object",
                }
            )
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            problems.append(
                {
                    "field_name": "objects",
                    "index": index,
                    "message": f"objects[{index}].name must be a non-empty string",
                }
            )
            continue
        concepts = item.get("concepts")
        if not isinstance(concepts, list):
            problems.append(
                {
                    "field_name": "objects",
                    "index": index,
                    "message": f"objects[{index}].concepts must be a list",
                }
            )
            continue
        normalized_concepts: list[str] = []
        concept_problem = False
        for concept_index, concept_id in enumerate(concepts):
            if not isinstance(concept_id, str) or not CONCEPT_ID_PATTERN.match(concept_id):
                problems.append(
                    {
                        "field_name": "objects",
                        "index": index,
                        "message": (
                            f"objects[{index}].concepts[{concept_index}] must be a "
                            "concept_id string like C-001"
                        ),
                    }
                )
                concept_problem = True
                break
            normalized_concepts.append(concept_id)
        if concept_problem:
            continue
        normalized.append({"name": name, "concepts": normalized_concepts})
    return normalized, problems


def validate_as_objects(fields: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate the canonical ``fields.objects`` shape of a level-5 step."""
    _normalized, problems = normalize_as_object_declarations(
        fields, allow_legacy_strings=False
    )
    return problems
