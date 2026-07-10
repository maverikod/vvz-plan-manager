"""Delegated authoring method documentation for the info command (C-013)."""

from typing import Any


def delegated_authoring_method_reference() -> dict[str, Any]:
    """Return the technical documentation of the delegated authoring method.

    Documents concept C-013 (DelegatedAuthoringMethod) and its exposure
    through concept C-012 (SelfDocumentedTechnology): the common-and-specific
    context compilation method, the orchestrator/per-branch-former/
    per-atomic-coder roles, and the zero-assumption escalation discipline
    under which an agent either produces its artifact from the material it
    was given or escalates the missing information to its parent.
    """
    return {
        "purpose": (
            "Document the top-down authoring and delegation method so an agent "
            "obtains the working method by reference to the planner's own "
            "information surface rather than external files (C-013), exposed "
            "through the self-documented information surface (C-012)."
        ),
        "concept": {
            "concept_id": "C-013",
            "name": "DelegatedAuthoringMethod",
            "definition": (
                "The documented top-down authoring and delegation method served "
                "through the planner's information surface."
            ),
            "properties": [
                "Documents the common-and-specific context compilation.",
                "Documents the orchestrator, per-branch former, and per-atomic "
                "coder roles.",
                "Lets an agent obtain the working method by reference to the "
                "information surface rather than external files.",
                "Enforces a zero-assumption rule: an agent either produces its "
                "artifact from the given material or escalates the gap to its "
                "parent, up through the orchestrator to the human; guessing to "
                "fill a gap is forbidden.",
            ],
        },
        "context_compilation_method": (
            "Authoring context is split into common parent material, compiled once "
            "for a parent node, and child-specific deltas that narrow attention to "
            "child scope and contain only material not already present in the "
            "common block."
        ),
        "delegation_roles": {
            "orchestrator": (
                "Owns the global execution map, assigns one global-step/"
                "tactical-step branch at a time, and verifies the reports it "
                "receives back."
            ),
            "per_branch_former": (
                "Forms and verifies the context for exactly one global-step/"
                "tactical-step branch, and delegates the atomic-step work of "
                "that branch."
            ),
            "per_atomic_coder": (
                "Executes exactly one target-file change for one atomic step and "
                "reports its verification result."
            ),
        },
        "zero_assumption_escalation": (
            "Every agent in the hierarchy either produces its artifact from the "
            "material it was given or escalates the missing information to its "
            "parent, and such escalation propagates upward through the "
            "orchestrator to the human as the final authority; guessing to fill "
            "a gap is forbidden."
        ),
    }
