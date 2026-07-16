"""Per-field content-fingerprint foundation over step fields (C-005).

Provides the reusable per-field content-hashing primitives used by the
step_xref command (duplicate-content detection across step prompts) and,
later, by the cache-integrity half of step_prompt_verify (CR-3). Every
function in this module is a pure, read-only computation: none of them
mutate the database or the Step objects passed to them.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.storage.canonical import content_hash

def step_field_hash(step: Step, field_name: str) -> str:
    """Compute the content-fingerprint hash of one field of one step.

    Args:
        step: The Step whose field is hashed.
        field_name: Key into step.fields whose value is hashed.

    Returns:
        content_hash(step.fields[field_name]): the SHA-256 hex digest of
        the canonical JSON encoding of that field's value.

    Raises:
        KeyError: When field_name is not a key of step.fields.
    """
    return content_hash(step.fields[field_name])

def step_field_hashes(step: Step) -> dict[str, str]:
    """Compute the content-fingerprint hash of every field of one step.

    Args:
        step: The Step whose fields are hashed.

    Returns:
        Dict mapping each key of step.fields to
        content_hash(step.fields[key]). Empty dict when step.fields is
        empty.
    """
    return {name: content_hash(value) for name, value in step.fields.items()}

def build_field_hash_index(
    nodes: dict[uuid.UUID, Step],
) -> dict[str, list[tuple[uuid.UUID, str]]]:
    """Build the plan-wide index mapping content hash to its locations.

    Args:
        nodes: Every step of the plan, keyed by uuid (as returned by
            plan_manager.views.dependency_graph.load_steps).

    Returns:
        Dict mapping each distinct field content hash (as computed by
        step_field_hash) to the list of (step_uuid, field_name)
        locations sharing that hash. Locations are appended in the
        iteration order of nodes and then of each step's fields dict;
        this index performs no sorting or canonical-path resolution,
        which is the caller's responsibility. A hash matched by no
        step's field never appears as a key.
    """
    index: dict[str, list[tuple[uuid.UUID, str]]] = {}
    for step_uuid, step in nodes.items():
        for field_name, value in step.fields.items():
            digest = content_hash(value)
            index.setdefault(digest, []).append((step_uuid, field_name))
    return index
