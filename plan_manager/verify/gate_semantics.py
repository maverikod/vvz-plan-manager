"""Per-check semantic glosses for the mechanical gate (todo d8849951).

Split out of ``verify.gate`` by EIG block F (todo 763ae29e) purely to keep
that orchestrator under the repository's hard ~400-line-per-file cap
(pinned by tests/test_plan_structure.py) once the block's four existence
check_ids were registered -- the same cap-driven split that already produced
``gate_execution_closure.py`` and ``gate_execution_existence.py``. This is a
verbatim move of the ``GATE_CHECK_SEMANTICS`` table with no content change;
``verify.gate`` re-exports the name, so
``from plan_manager.verify.gate import GATE_CHECK_SEMANTICS`` keeps working
for both metadata modules and the tests that pin it.
"""

from __future__ import annotations

# One-line semantic gloss per gate check, for embedding in command metadata/
# help (todo d8849951) so a caller can interpret gate_report_json findings
# without reading these check functions' docstrings. Every gloss states the
# comparison direction explicitly (which side is "required" and which side
# is "covering") to avoid the "missing" misreading that caused bugs 3de7a081
# and a8c43201: the gate always evaluates the plan's LIVE, current state
# (including any open cascade's working tip) -- never a stale or persisted
# snapshot. Scope is the coverage.* family plus the references.* family
# (the two families a caller is most likely to need explained to interpret
# a finding; the remaining checks' messages are self-explanatory).
GATE_CHECK_SEMANTICS: dict[str, str] = {
    "coverage.concepts": (
        "Every concept in the plan's concept table (MRS) must be declared "
        "on at least one GS step's own concepts; flags a concept not "
        "covered by any GS step, or a GS-declared concept with no matching "
        "row in the concept table ('extra')."
    ),
    "coverage.gs": (
        "Every concept a GS step declares on itself must be covered by the "
        "union of its own level-4 (TS) children's concepts; flags a "
        "GS-declared concept not covered by any child (TS) step's own "
        "decomposition -- NOT a statement that the concept is missing from "
        "the GS row itself (it is still there; it just is not yet covered "
        "by a TS child)."
    ),
    "coverage.labels": (
        "Every binding HRS paragraph label must be claimed by at least one "
        "GS step's source_labels; flags an HRS label not covered by any GS "
        "step, or a GS-claimed label with no matching binding HRS "
        "paragraph ('extra')."
    ),
    "coverage.relations": (
        "Every relation row in the plan's relation table (MRS) must be "
        "implemented by at least one GS step's own relations field; flags "
        "a relation not covered by any GS step, or a GS-declared relation "
        "with no matching row in the relation table ('extra')."
    ),
    "coverage.object_multiple_owner_keys": (
        "An object name declared by atomic steps must map to exactly one "
        "owner key (module plus tactical-step path). The gate flags the "
        "participating atomic steps when the same object name is defined "
        "under more than one owner key."
    ),
    "coverage.object_multiple_modules": (
        "An object name declared by atomic steps must stay within one "
        "module. The gate flags the participating atomic steps when the "
        "same object name drifts across multiple target-file-derived modules."
    ),
    "coverage.object_concepts_not_covered": (
        "Every declared object's concept set must be a subset of the union "
        "of the concept sets on the atomic steps that declare it. The gate "
        "flags participating atomic steps when an object declaration names "
        "concepts not covered by those atomic-step concept sets."
    ),
    "references.depends_on": (
        "Every step's depends_on entries must resolve to a sibling step_id "
        "(same level, same parent) that exists in the full plan tree."
    ),
    "references.concepts": (
        "Every step's own concepts entries must resolve to a concept_id "
        "defined in the plan's concept table (MRS)."
    ),
    "references.relations": (
        "Every relation row in the plan's relation table (MRS) must have "
        "both from_concept/to_concept resolve to a defined plan concept "
        "and a type that is one of the supported relation types."
    ),
    "references.source_labels": (
        "Every source_labels entry a step declares must resolve to a "
        "binding HRS paragraph label defined in the plan."
    ),
}

