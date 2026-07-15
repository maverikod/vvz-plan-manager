"""Concept domain entity (MRS concept C-003).

A Concept is an MRS entry with a C-NNN identifier unique within the plan,
a canonical name, a one-sentence definition, a list of properties, and
source labels referencing the HRS paragraphs (C-002) that justify it.
Concepts are selected to be as orthogonal as possible.

"""

import re

from dataclasses import dataclass

from typing import List

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck


CONCEPT_ID_PATTERN = re.compile(r"^C-\d{3}$")

PARAGRAPH_LABEL_PATTERN = re.compile(r"^\{[0-9a-z]{4}\}$")


class ConceptValidationError(ValueError):
    """Raised when a Concept fails write-time validation."""


@dataclass
class Concept(DataclassEntity):
    """A single MRS concept entry.

    Attributes:
        concept_id: Identifier matching pattern C-NNN (e.g. "C-003"),
            unique within the plan.
        name: Canonical short name of the concept.
        definition: One-sentence definition of the concept.
        properties: List of property strings describing the concept.
        source_labels: List of HRS paragraph labels (C-002) that justify
            the concept, each formatted as a four-character base36 string
            wrapped in curly braces, e.g. "{k2p7}".
    """

    ENTITY_TYPE = "concept"
    ENTITY_ID_FIELD = "concept_id"
    TABLE_NAME = "concept"
    ID_COLUMN = None
    ID_COLUMNS = ("plan_uuid", "concept_id")
    SOFT_DELETE_COLUMN = None
    HARD_DELETE_REFERENCE_CHECKS = (
        ReferenceCheck("relation", "from_concept", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),)),
        ReferenceCheck("relation", "to_concept", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),)),
        ReferenceCheck("step", "concepts", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),), array=True),
    )

    concept_id: str
    name: str
    definition: str
    properties: List[str]
    source_labels: List[str]


def validate_concept(concept: Concept) -> None:
    """Validate a Concept's fields at write time.

    Args:
        concept: The Concept instance to validate.

    Raises:
        ConceptValidationError: If any of the following hold:
            - concept.concept_id does not match CONCEPT_ID_PATTERN
              (pattern "^C-\\d{3}$", e.g. "C-003").
            - concept.name is empty or consists only of whitespace.
            - concept.definition is empty or consists only of whitespace.
            - concept.properties is not a list.
            - any element of concept.properties is not a string, or is a
              string that is empty or consists only of whitespace.
            - concept.source_labels is not a list.
            - any element of concept.source_labels is not a string, or
              does not match PARAGRAPH_LABEL_PATTERN (pattern
              "^\\{[0-9a-z]{4}\\}$", e.g. "{k2p7}").
    """
    if not CONCEPT_ID_PATTERN.match(concept.concept_id):
        raise ConceptValidationError(
            f"concept_id '{concept.concept_id}' does not match pattern "
            f"'{CONCEPT_ID_PATTERN.pattern}'"
        )
    if not concept.name.strip():
        raise ConceptValidationError("name must not be empty")
    if not concept.definition.strip():
        raise ConceptValidationError("definition must not be empty")
    if not isinstance(concept.properties, list):
        raise ConceptValidationError("properties must be a list")
    for item in concept.properties:
        if not isinstance(item, str) or not item.strip():
            raise ConceptValidationError(
                "each property must be a non-empty string"
            )
    if not isinstance(concept.source_labels, list):
        raise ConceptValidationError("source_labels must be a list")
    for label in concept.source_labels:
        if not isinstance(label, str) or not PARAGRAPH_LABEL_PATTERN.match(label):
            raise ConceptValidationError(
                f"source label '{label}' does not match pattern "
                f"'{PARAGRAPH_LABEL_PATTERN.pattern}'"
            )


def check_concept_id_unique(
    concept_id: str, existing_concept_ids: List[str]
) -> None:
    """Check that a concept_id is not already present in the plan.

    Args:
        concept_id: The candidate concept_id, expected to match
            CONCEPT_ID_PATTERN (format is not re-checked by this
            function).
        existing_concept_ids: List of concept_id strings already present
            in the plan (excluding the candidate itself).

    Raises:
        ConceptValidationError: If concept_id is present in
            existing_concept_ids.
    """
    if concept_id in existing_concept_ids:
        raise ConceptValidationError(
            f"concept_id '{concept_id}' is not unique within the plan"
        )
