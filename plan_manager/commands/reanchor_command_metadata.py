"""Shared metadata fragment for the reanchor command pair (bug_reanchor, todo_reanchor; C-012 part b)."""

from __future__ import annotations

REANCHOR_ERROR_CASES: dict[str, dict[str, str]] = {
    "FROZEN_TRUTH_WRITE": {
        "description": "The candidate new anchor target is a plan or a step whose status is frozen; a re-anchor move never targets frozen-truth.",
        "message": "cannot re-anchor onto frozen plan truth: {details}",
        "solution": "Choose a candidate new target whose plan or step status is not frozen.",
    },
}

REANCHOR_BEST_PRACTICES: list[str] = [
    "The candidate new anchor is validated under the identical rules the entity's create command uses for its anchor; supply the same identifier fields that command would require for the chosen kind.",
    "A successful re-anchor overwrites the entity's stored anchor and appends one immutable runtime audit record capturing the actor and the prior-anchor-to-new-anchor transition; there is no separate preview step.",
]
