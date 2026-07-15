"""Relation domain entity (MRS concept C-004).


A Relation is a typed directed edge from one Concept (C-003) to another,
restricted to exactly seven types: uses, owns, implements, extends,
depends_on, produces, consumes. Free-form types are rejected at write
time. A Relation depends on the existence of the Concepts (identified by
concept_id, pattern C-NNN) it connects. Self-referencing relations (a
concept related to itself) are permitted.

"""


from dataclasses import dataclass

from typing import List

from plan_manager.domain.concept import CONCEPT_ID_PATTERN
from plan_manager.domain.entity import DataclassEntity


RELATION_TYPES = frozenset(
    {"uses", "owns", "implements", "extends", "depends_on", "produces", "consumes"}
)


class RelationValidationError(ValueError):
    """Raised when a Relation fails write-time validation."""


@dataclass
class Relation(DataclassEntity):
    """A single typed directed edge between two concepts.

    Attributes:
        from_concept: concept_id (pattern C-NNN) of the source concept.
        to_concept: concept_id (pattern C-NNN) of the target concept.
        type: Relation type; must be one of RELATION_TYPES.
    """

    ENTITY_TYPE = "relation"
    ENTITY_ID_FIELDS = ("from_concept", "type", "to_concept")
    TABLE_NAME = "relation"
    ID_COLUMN = None
    ID_COLUMNS = ("plan_uuid", "from_concept", "to_concept", "type")
    SOFT_DELETE_COLUMN = None

    from_concept: str
    to_concept: str
    type: str


def validate_relation(relation: Relation) -> None:
    """Validate a Relation's fields at write time.

    Args:
        relation: The Relation instance to validate.

    Raises:
        RelationValidationError: If any of the following hold:
            - relation.type is not a member of RELATION_TYPES (the set
                {"uses", "owns", "implements", "extends", "depends_on",
                "produces", "consumes"}).
            - relation.from_concept does not match CONCEPT_ID_PATTERN
                (pattern "^C-\\d{3}$", e.g. "C-003").
            - relation.to_concept does not match CONCEPT_ID_PATTERN
                (pattern "^C-\\d{3}$", e.g. "C-003").
    """
    if relation.type not in RELATION_TYPES:
        raise RelationValidationError(
            f"type '{relation.type}' is not one of {sorted(RELATION_TYPES)}"
        )
    if not CONCEPT_ID_PATTERN.match(relation.from_concept):
        raise RelationValidationError(
            f"from_concept '{relation.from_concept}' does not match "
            f"pattern '{CONCEPT_ID_PATTERN.pattern}'"
        )
    if not CONCEPT_ID_PATTERN.match(relation.to_concept):
        raise RelationValidationError(
            f"to_concept '{relation.to_concept}' does not match pattern "
            f"'{CONCEPT_ID_PATTERN.pattern}'"
        )


def check_relation_endpoints_exist(
    relation: Relation, existing_concept_ids: List[str]
) -> None:
    """Check that both endpoints of a Relation reference existing concepts.

    Args:
        relation: The Relation instance whose endpoints are checked.
        existing_concept_ids: List of concept_id strings currently
            present in the plan.

    Raises:
        RelationValidationError: If relation.from_concept is not present
            in existing_concept_ids, or if relation.to_concept is not
            present in existing_concept_ids.
    """
    if relation.from_concept not in existing_concept_ids:
        raise RelationValidationError(
            f"from_concept '{relation.from_concept}' does not reference "
            f"an existing concept"
        )
    if relation.to_concept not in existing_concept_ids:
        raise RelationValidationError(
            f"to_concept '{relation.to_concept}' does not reference "
            f"an existing concept"
        )
