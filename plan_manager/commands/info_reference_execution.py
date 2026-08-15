"""Execution-integrity reference data for the info command (EIG blocks A..G).

The Execution Integrity Gate work added a SECOND axis to the mechanical gate.
Everything the gate asked before it -- parse, identity, uniqueness,
references, coverage, embedded code, context coverage -- judges the plan as an
AUTHORING ARTIFACT. The ``execution_integrity`` group judges the same plan as
an EXECUTION PROGRAM. This module is the single authoritative passage telling
an executing agent how the two differ, what vocabulary the second axis uses,
how it degrades when the external world cannot be read, and what it may and
may not do to plan truth. Consumed by ``plan_manager.commands.info_command``
for the capabilities section.
"""

from __future__ import annotations

from typing import Any


def execution_integrity_capabilities() -> dict[str, Any]:
    """The capabilities-section descriptor for the execution-integrity group."""
    return {
        "summary": (
            "The mechanical gate reports THREE contours over one run: "
            "structural (is this a well-formed authoring artifact), execution "
            "(is this a runnable, ordered, closed program), and semantic (is "
            "this complete against the specification, measured separately by "
            "the scoring layer). Every gate surface reports the same "
            "'contours' block, derived from the single gate report it already "
            "ran -- never from a second gate pass."
        ),
        "semantic_coverage_vs_execution_closure": {
            "distinction": (
                "SEMANTIC COVERAGE asks whether every concept, label, and "
                "relation of the specification is realized by some step: it is "
                "a question about MEANING, answered by the coverage checks and, "
                "quantitatively, by plan_score's SemanticIndex. EXECUTION "
                "CLOSURE asks whether the steps, taken as a program, can "
                "actually run to completion: whether every consumed object has "
                "a producer ordered before it, whether the combined "
                "explicit+inferred graph is acyclic, whether producer and "
                "consumer can be placed in the same parallel wave, whether "
                "tests, release artifacts, and deployments close over what they "
                "claim, and whether the files a step verifies or modifies exist "
                "anywhere. A plan can be fully covered and completely "
                "unrunnable, and vice versa. Do not read one as evidence of the "
                "other."
            ),
            "structural_contour": "Every gate check whose check_id is NOT prefixed 'execution_integrity.'.",
            "execution_contour": "Every gate check whose check_id IS prefixed 'execution_integrity.'.",
            "semantic_contour": (
                "Not a gate check at all: the scoring layer's state at the "
                "surface reporting it -- 'scored' (plan_score/branch_weak just "
                "computed an index), 'deferred' (plan_status: scoring is "
                "queue-bound and not computed synchronously), 'refused' "
                "(scoring is never computed for a non-green gate), or "
                "'not_evaluated' (plan_validate, cascade_preview, "
                "plan_prompt_chain: gate-only surfaces that never consult "
                "scoring)."
            ),
            "invariant": "structural.green AND execution.green == the report's own green.",
        },
        "role_vocabulary": {
            "purpose": (
                "An atomic step declares fields.objects entries of the shape "
                "{name, concepts, role}. The role is what makes the execution "
                "graph derivable: it says whether this step BRINGS an object "
                "into existence or DEPENDS on it already existing."
            ),
            "roles": {
                "create": "Produces the object; the step is a producer and the object did not exist before.",
                "modify": "Produces a new state of an object that must already exist; producer for ordering, but never a creator for existence.",
                "consume": "Reads or builds on the object; the step is a consumer and must be ordered after a producer.",
                "verify": "Checks the object; a consumer for ordering purposes.",
                "document": "Describes the object; neither producer nor consumer of its content.",
                "package": "Packages the object into a distributable artifact.",
                "deploy": "Deploys the packaged artifact.",
            },
            "producers_consumers": (
                "object_inventory derives, per object name, 'producers' "
                "(role create or modify) and 'consumers' (role consume or "
                "verify). role is OPTIONAL: a legacy entry without one "
                "contributes to neither list and produces no inferred edge, "
                "which is exactly why a role-less plan authored before this "
                "work stays green."
            ),
        },
        "inferred_edge_provenance": {
            "purpose": (
                "execution_graph returns two edge sets over the same nodes. "
                "Provenance says where an edge came from and therefore how much "
                "authority it carries."
            ),
            "explicit": {
                "provenance": "explicit",
                "types": {
                    "explicit": "A declared depends_on edge: plan truth, authored by a human or a command.",
                    "file_order": "Deterministic same-file/cross-branch ordering derived from target_file plus priority.",
                },
                "authority": "Binding. The gate's checks test whether inferred edges are ALREADY implied by this set.",
            },
            "inferred": {
                "provenance": "inferred",
                "types": {
                    "object_producer": "producer -> consumer, derived from object role declarations; evidence names the object.",
                    "verification_target": "creator -> verifier, derived from an AS verification.target matching another AS's created target_file; evidence names the target.",
                },
                "authority": (
                    "Advisory. An inferred edge is a PROPOSAL about order, not a "
                    "dependency: it is never stored, never silently applied, and "
                    "never treated as satisfying an ordering requirement on its "
                    "own."
                ),
            },
        },
        "external_verification_modes": {
            "purpose": (
                "Four execution_integrity checks compare the plan against the "
                "live file inventory of the plan's PRIMARY analysis-server "
                "project. That inventory is fetched by the command layer (the "
                "gate itself performs no I/O) and handed down to the gate. Every "
                "gate caller -- plan_validate, plan_status, cascade_preview, "
                "cascade_commit, step_transition's freeze gate, "
                "plan_prompt_chain, and the scoring index -- resolves it the "
                "same way and degrades identically."
            ),
            "modes": {
                "ok": "The full project-relative inventory was read; the existence checks report real findings.",
                "skipped/no_primary_project": "The plan has no primary project binding (or it is not a UUID). No probe is fetched and every existence check stays silent.",
                "skipped/plan_unreadable": "The plan row could not be read at all on this path. Treated exactly like an absent binding: silent.",
                "unavailable/ca_unreachable": "The analysis server is unconfigured, unreachable, answered a shape this client does not understand, or the listing was too large to read completely.",
            },
            "degraded_policy": (
                "ABSENCE OF KNOWLEDGE IS NEVER A VIOLATION. With no probe, or an "
                "unavailable one, the existence checks emit nothing and the "
                "verdict is byte-identical to a run without external "
                "verification. The single exception is the operator policy "
                "require_project_verification: when it is set AND the probe was "
                "attempted but unavailable, the gate emits exactly ONE "
                "plan-level finding "
                "(execution_integrity.external_project_unverified) saying so, "
                "rather than inventing per-step verdicts from a failed read. A "
                "partial inventory is always reported as unavailable, never as "
                "a smaller project."
            ),
            "surface": "The 'external_verification' key on plan_validate, plan_status.gate, and cascade_preview reports which mode applied.",
        },
        "no_silent_truth_writes": {
            "rule": (
                "The gate, the execution graph, and every inferred edge are "
                "READ-ONLY over plan truth. Nothing in this axis ever writes a "
                "depends_on edge, a role, a status, or a revision as a side "
                "effect of being run or of being right."
            ),
            "only_write_path": (
                "execution_dependency_suggest computes the unambiguous, "
                "not-already-implied inferred edges as a "
                "step_dependency_apply-compatible proposal and writes nothing; "
                "execution_dependency_apply materializes an explicitly approved "
                "proposal as one revision under the ordinary mutation-admission "
                "regime (a frozen target still requires an open cascade). "
                "suggest/apply is the ONLY path from an inferred edge to plan "
                "truth."
            ),
            "consequence": (
                "Re-running plan_validate can never make a red execution "
                "contour go green. Closing an ordering finding requires the "
                "apply step -- which is a deliberate, auditable, reversible "
                "act, not a gate side effect."
            ),
        },
        "diagnostic_override": {
            "command": "plan_prompt_chain",
            "parameter": "diagnostic_override (boolean, default false)",
            "refusal_matrix": {
                "structural_red": "Refused with GATE_RED, always, regardless of diagnostic_override. A malformed authoring artifact cannot yield a meaningful prompt chain.",
                "execution_red_structural_green": "Refused with EXECUTION_RED by default; admitted when diagnostic_override=true.",
                "both_green": "Assembled normally.",
            },
            "when_overridden": (
                "The payload is never silent about it: it carries "
                "diagnostic_override=true plus an execution_findings summary "
                "(findings_count and up to five top findings) alongside the "
                "usual contours block, so any consumer can see that this chain "
                "describes a plan whose execution order is not guaranteed."
            ),
            "intended_use": (
                "A diagnostic escape hatch for inspecting a plan whose "
                "execution program is still being closed -- not a normal "
                "execution path. Wave-parallel execution of an overridden chain "
                "is unsafe by construction, because the very findings it "
                "carries are the ones that would have ordered it."
            ),
        },
        "domain_errors": {
            "GATE_RED": "The structural gate contour is not green; no partial payload is returned and no override exists.",
            "EXECUTION_RED": "The structural contour is green but the execution-integrity contour is not: the plan is a well-formed authoring artifact whose execution program is unordered, unclosed, or ungrounded. Raised by plan_prompt_chain and admitted deliberately with diagnostic_override=true.",
        },
    }
