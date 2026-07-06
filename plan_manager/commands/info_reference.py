"""Structured reference data returned by the info command."""

from typing import Any


def project_binding_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for project binding APIs."""
    return {
        "purpose": (
            "Optional external UUID anchors from planmgr plans "
            "and steps to analysis-server projects. planmgr stores "
            "only project_id UUID strings and does not maintain a "
            "project catalog."
        ),
        "plan_fields": {
            "project_ids": "List of bound analysis-server project UUIDs.",
            "primary_project_id": "Optional leading project UUID; must be in project_ids when set.",
        },
        "step_fields": {
            "project_id": (
                "Optional top-level project UUID on GS/TS/AS steps. "
                "No inheritance is implied from plan, GS, or TS."
            )
        },
        "commands": {
            "plan_project_attach": {
                "mutates": True,
                "summary": "Attach project_id to plan.project_ids; idempotent; primary=true also sets primary_project_id.",
            },
            "plan_project_detach": {
                "mutates": True,
                "summary": "Remove project_id from the plan, clear primary when matching, and clear all step.project_id bindings to it.",
            },
            "plan_project_list": {
                "mutates": False,
                "summary": "Return plan_uuid, project_ids, and primary_project_id.",
            },
            "plan_project_set_primary": {
                "mutates": True,
                "summary": "Set primary_project_id to an already attached project_id; does not attach implicitly.",
            },
            "plan_project_clear_primary": {
                "mutates": True,
                "summary": "Clear primary_project_id without changing plan.project_ids or step.project_id.",
            },
            "step_create": {
                "mutates": True,
                "project_id_behavior": "Optional top-level project_id; if omitted, stores null; if supplied, must already be bound to the plan.",
            },
            "step_update": {
                "mutates": True,
                "project_id_behavior": "Omitted project_id leaves binding unchanged; UUID sets it; null clears it.",
            },
        },
        "read_surfaces": {
            "plan_status": "Returns projects.count, projects.project_ids, and projects.primary_project_id.",
            "plan_list": "Returns project_count and primary_project_id for each plan.",
            "step_get": "Returns top-level project_id.",
            "step_tree": "Returns project_id for every tree entry.",
            "branch_prompt": "Includes plan project bindings and the current atomic step project context.",
            "plan_prompt_chain": "Includes plan project bindings and project_id for each included atomic step.",
            "plan_export": "Writes project_ids, primary_project_id, and each step project_id.",
            "plan_import": "Restores project_ids, primary_project_id, and step project_id; step project_id must be listed in imported project_ids.",
        },
        "domain_errors": {
            "INVALID_PROJECT_ID": "project_id or primary_project_id is not a UUID.",
            "PROJECT_NOT_BOUND_TO_PLAN": "A step or primary operation references a project not in plan.project_ids.",
            "PROJECT_NOT_ATTACHED_TO_PLAN": "Detach was requested for a project not currently attached to the plan.",
            "PRIMARY_PROJECT_NOT_BOUND": "primary_project_id is set but absent from project_ids.",
            "DUPLICATE_PROJECT_BINDING": "project_ids contains duplicate UUIDs.",
        },
        "invariants": [
            "A plan may have zero, one, or many project_ids.",
            "primary_project_id is optional; when set, it must be present in project_ids.",
            "step.project_id is optional and must be present in plan.project_ids when set.",
            "Project bindings are context metadata, not HRS/MRS/GS/TS/AS normative content.",
            "planmgr does not verify analysis-server project existence in the MVP.",
        ],
    }


def context_block_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for context-block APIs."""
    return {
        "purpose": (
            "Read-only, cascade-aware authoring context compilation from MRS "
            "concept ids. The API stores typed derived ContextBlock records in "
            "the database and returns them inline over JSON-RPC; it never writes "
            "files under export_root and never advances plan head."
        ),
        "record_model": {
            "ContextBlock": {
                "block_id": "UUID primary identity of the stored derived block.",
                "plan_uuid": "Owning plan UUID.",
                "revision_uuid": "Head or cascade-tip revision the block was compiled against.",
                "cascade_uuid": "Open cascade UUID when compiled against working state; otherwise null.",
                "node_path": "Parent step path or 'plan'.",
                "child_level": "Target child level: 3 for GS, 4 for TS, 5 for AS.",
                "kind": "compile, common, or specific.",
                "common_block_id": "Referenced common block for specific blocks; null otherwise.",
                "scope_concepts": "Sorted concept ids that define this block's semantic scope.",
                "content_hash": "SHA-256 of canonical JSON content; excludes block_id and created_at.",
                "content": "Ordered typed content blocks.",
            },
            "content_block_types": [
                "authoring_template",
                "standards",
                "field_schema",
                "step_definition",
                "hrs_fragment",
                "mrs_concept",
                "mrs_relation",
            ],
            "canonical_order": [
                "authoring_template",
                "standards",
                "field_schema",
                "step_definition",
                "hrs_fragment",
                "mrs_concept",
                "mrs_relation",
            ],
        },
        "commands": {
            "context_compile": {
                "mutates_plan_truth": False,
                "stores_derived_record": True,
                "summary": "Compile a standalone context block directly from concept ids.",
            },
            "context_common": {
                "mutates_plan_truth": False,
                "stores_derived_record": True,
                "summary": "Compile the shared parent context for authoring children.",
            },
            "context_specific": {
                "mutates_plan_truth": False,
                "stores_derived_record": True,
                "summary": "Compile a child-specific delta over an existing common block.",
            },
            "context_bundle": {
                "mutates_plan_truth": False,
                "stores_derived_record": True,
                "summary": "Compile one common block first, then ordered child-specific deltas.",
            },
            "block_get": {
                "mutates_plan_truth": False,
                "summary": "Return one stored ContextBlock by block_id.",
            },
            "block_list": {
                "mutates_plan_truth": False,
                "summary": "List stored ContextBlock summaries by plan, node, kind, revision, or cascade.",
            },
        },
        "compilation_rules": {
            "concept_join_key": "Caller supplies concept ids; planmgr resolves all HRS/MRS material from plan truth.",
            "hrs_fragments": "Union of source_labels for supplied concepts, deduped by label.",
            "mrs_concepts": "One block per supplied concept id, deduped and sorted.",
            "mrs_relations": "Relations whose from_concept is inside scope; to_concept may be outside scope as a bare reference.",
            "common_default_scope": "For node='plan', all plan concepts; for a step node, that step's top-level concepts unless shared_concepts is supplied.",
            "specific_delta": "Specific blocks remove any hrs_fragment, mrs_concept, or mrs_relation already present in the referenced common block.",
            "scope_identity": "Specific blocks with identical empty delta content remain distinct when scope_concepts differ.",
        },
        "invariants": [
            "context_common must be created before context_specific.",
            "specific concepts must be a subset of common.scope_concepts.",
            "Compilation is read-only over HRS, MRS, steps, head revision, gates, and cascade state.",
            "Derived block storage is idempotent for the same plan, revision or cascade, node_path, child_level, kind, common_block_id, scope_concepts, and content_hash.",
            "Use cascade_uuid to compile against open-cascade working state; omit it for current head.",
        ],
        "domain_errors": {
            "NODE_NOT_FOUND": "node is not 'plan' and does not resolve to a step.",
            "CONCEPT_NOT_FOUND": "A supplied concept id is absent from the plan MRS.",
            "CONCEPT_OUT_OF_SCOPE": "Specific child concepts are not within common.scope_concepts.",
            "COMMON_BLOCK_NOT_FOUND": "common_block_id is absent, from another plan, or not a common block.",
            "INVALID_LEVEL": "child_level is not one of 3, 4, or 5.",
            "REVISION_NOT_FOUND": "Explicit revision is not available for live context compilation.",
            "CASCADE_CONFLICT": "cascade_uuid is not the plan's open cascade, or revision and cascade_uuid were both supplied.",
        },
    }


def planning_standards_reference() -> dict[str, Any]:
    """Return a compact glossary of planning standard terms for agents."""
    return {
        "source_files": [
            "docs/standards/planning/plan_standard_machine.yaml",
            "docs/standards/planning/hrs_mrs_gs_consistency_verification_standard.yaml",
            "docs/standards/planning/tactical_step_creation_standard.yaml",
            "docs/standards/planning/atomic_step_creation_standard.yaml",
            "docs/standards/planning/atomic_step_execution_standard.yaml",
            "docs/standards/planning/metadatastd.yaml",
        ],
        "core_principles": {
            "semantic_reproduction": (
                "The sum of children semantically reproduces the parent. "
                "Levels 1-2 define what the system is; levels 3-5 define how it will be implemented."
            ),
            "top_down_change": "All normative changes flow top-down through the cascade discipline.",
            "zero_trust": "Verification and authoring passes re-read source artifacts in full before each check; memory of previous reads is stale.",
            "computed_views_only": "Coverage matrices and traceability views are computed on demand and never written as files.",
            "human_owned_hrs": "source_spec.md is human-owned prose; procedures may label or mark non-binding text but do not rewrite binding content.",
        },
        "artifact_levels": {
            "HRS": {
                "level": 1,
                "canonical_name": "source_spec",
                "path": "docs/plans/<plan_name>/source_spec.md",
                "meaning": "Human-readable source specification and source of truth.",
                "unit": "Binding paragraph with a stable label such as {a3f9}.",
                "mutability": "Human-owned; normative content changes trigger cascade.",
            },
            "MRS": {
                "level": 2,
                "canonical_name": "machine_spec",
                "path": "docs/plans/<plan_name>/spec.yaml",
                "meaning": "Machine-readable projection of HRS into concepts and typed relations.",
                "unit": "concept_id and relation.",
                "forbidden_content": [
                    "implementation details",
                    "action sequences",
                    "alternatives or open questions",
                    "free prose",
                ],
            },
            "GS": {
                "level": 3,
                "canonical_name": "global_step",
                "path": "docs/plans/<plan_name>/G-NNN-<slug>/README.yaml",
                "meaning": "Conceptual block describing domain objects and operations without file/function details.",
                "required_shape": [
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
            },
            "TS": {
                "level": 4,
                "canonical_name": "tactical_step",
                "path": "docs/plans/<plan_name>/G-NNN-<slug>/T-NNN-<slug>/README.yaml",
                "meaning": "Refinement of one GS into concrete entities and actions; still not file/function implementation.",
                "required_shape": [
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
            },
            "AS": {
                "level": 5,
                "canonical_name": "atomic_step",
                "path": "docs/plans/<plan_name>/G-NNN-<slug>/T-NNN-<slug>/atomic_steps/A-NNN-<slug>.yaml",
                "meaning": "Self-contained implementation prompt for one indivisible code change touching exactly one code file.",
                "required_shape": [
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
        },
        "mrs_terms": {
            "concept": "Entity with behavior or invariant; plain properties are not concepts unless they have behavior.",
            "concept_id": "Stable C-NNN identifier unique within one plan.",
            "source_labels": "HRS paragraph labels that justify a concept.",
            "relation": "Typed edge between concepts.",
            "allowed_relation_types": [
                "uses",
                "owns",
                "implements",
                "extends",
                "depends_on",
                "produces",
                "consumes",
            ],
        },
        "coverage_axes": {
            "concept_axis": (
                "Semantic axis. Unit is an MRS concept. Completeness means every concept is covered by at least one step; "
                "concept overlap is allowed and is a semantic link, not duplicated work."
            ),
            "object_work_axis": (
                "Implementation axis. Unit is a concrete object or work unit. Independence means no two steps create or modify "
                "the same object or do the same work on the same target."
            ),
            "do_not_conflate": "No gaps belongs to the concept axis; no overlaps belongs to the object/work axis.",
        },
        "computed_views": {
            "gs_concept_coverage": "Computed from GS READMEs; verifies every MRS concept is covered by at least one GS.",
            "ts_concept_coverage": "Computed per GS; verifies every GS concept is realized by at least one TS.",
            "concept_object_inventory": "Computed source-derived map from concepts to required packages, modules, classes, functions, constants, configs, and generated artifacts.",
            "concept_as_traceability": "Computed map from concepts to AS files and concrete objects that realize them.",
            "object_coverage": "Computed object/work view showing which AS realizes which concrete object or work unit.",
            "context_block": "Stored derived authoring-context view compiled from concept ids; not a normative artifact and not exported as a file.",
            "common_context_block": "Shared parent context for child authoring: baked template, standards, field schema, optional parent step definition, and compiled concept material for the inherited scope.",
            "specific_context_block": "Child-specific delta over a common block; narrows attention to child scope and contains only HRS/MRS material not already present in common.",
        },
        "verification_cycles": {
            "cycle_1_source_to_machine_alignment": {
                "purpose": "Verify MRS faithfully represents HRS and every binding HRS thesis is covered.",
                "checks": [
                    "machine concepts and relations are justified by HRS source_labels",
                    "binding HRS theses are represented in MRS",
                    "relation types are one of the allowed seven",
                    "concepts are behavior/invariant entities",
                    "computed GS concept coverage has no empty concept column",
                ],
            },
            "cycle_2_global_step_triple_autonomy": {
                "purpose": "Verify each HRS + MRS + GS triple is enough for an executor without sibling GS content.",
                "checks": [
                    "concept and relation references are valid",
                    "source_labels are relevant",
                    "executor completeness",
                    "no silent dependency on sibling GS",
                    "no bare redundancy with upper levels",
                ],
            },
            "tactical_triple": "For each TS, verify MRS + parent GS + TS is self-contained and independent from sibling TS.",
            "atomic_quadruple": "For each AS, verify MRS + parent GS + parent TS + AS prompt is self-contained for a coder model.",
        },
        "authoring_terms": {
            "tezis": "Coherent semantic claim in HRS; may map to a concept, relation, or property in MRS.",
            "detailed_expansion": "Executor-facing elaboration in a GS that expands an MRS thesis.",
            "drift": "Discrepancy between levels: orphan concept, missing thesis, insufficient step, or redundant step.",
            "green_pass": "Full traversal of a verification loop with an empty finding list.",
            "overall_green": "Required verification cycles are green under the same MRS snapshot.",
            "finding": "A concrete standards violation found by a check.",
            "escalation": "Stop and return to the correct upper level or human when a finding cannot be fixed at the current layer.",
            "scope_concepts": "The sorted concept ids defining the semantic scope of a compiled authoring context block.",
            "downward_narrowing": "A child context scope must be a subset of its parent common scope; violations are rejected as CONCEPT_OUT_OF_SCOPE.",
            "common_delta_split": "Authoring context is split into common parent material and child-specific deltas so shared material is emitted once.",
            "derived_record": "Database record computed from plan truth; it is cached and addressable but does not change HRS, MRS, steps, gates, cascade state, or head revision.",
        },
        "tactical_terms": {
            "entity": "Concrete domain object named by TS: class, module boundary, data schema, API contract, or config object.",
            "action": "Concrete operation on entities: create, modify, route, validate, transform, register, expose.",
            "overlap": "Two TSs create/modify the same entity or perform the same action on the same target; shared concept_id alone is not overlap.",
            "autonomy_criterion": "MRS + parent GS + one TS contains everything needed to act on that TS.",
            "independence_criterion": "Sibling TSs within one GS do not overlap in entities or actions.",
        },
        "atomic_terms": {
            "atomicity": "AS cannot be split without producing meaningless half-steps.",
            "one_file_rule": "One AS touches exactly one code file; one file may have multiple AS ordered by priority.",
            "target_file": "Exact project-relative code file path touched by the AS.",
            "priority": "Integer unique among AS targeting the same file within the same TS; execution order is ascending.",
            "context_budget": "Token ceiling for AS execution context: MRS excerpt, parent GS, parent TS, current file content, and AS prompt.",
            "verification": "Structured expected check for an AS: type, target, expected.",
            "allowed_operations": ["create_file", "modify_file", "delete_file", "rename_file"],
            "file_size_limit": "Target code files should stay below 400 lines, recommended 350; violations escalate to TS design.",
        },
        "execution_delegation": {
            "owner": "Primary orchestrator; owns global execution map, assigns one GS/TS branch, verifies reports.",
            "mini": "Context former and verifier for exactly one GS/TS branch; forms per-TS context and delegates AS work.",
            "spark": "One-AS coder; executes exactly one target-file change and reports verification.",
            "context_minimization": "Agents receive only the context needed for their level; sibling branch context is contamination unless explicitly required.",
            "target_file_lock": "AS touching the same file are serialized by priority; independent files may run in parallel.",
            "spawn_unavailable": "Mini must report SPAWN_UNAVAILABLE instead of coding directly when it cannot spawn spark.",
        },
        "status_terms": {
            "draft": "Editable planning artifact state.",
            "ready_for_review": "Artifact is prepared for review/freeze flow.",
            "frozen": "Artifact is no longer directly mutable; changes require cascade discipline.",
            "needs_review": "Cascade-propagated invalidation state; not a normal direct user target.",
            "in_progress": "Execution/runtime status for work underway; direct reachability depends on command transition model.",
            "done": "Completed atomic/runtime work state.",
        },
        "cascade_terms": {
            "cascade": "Top-down change propagation procedure used when upper-level changes affect lower levels.",
            "open_cascade": "A mutable cascade branch that admits changes under frozen artifacts.",
            "cascade_preview": "Computed gate/impact preview before committing cascade changes.",
            "cascade_commit": "Publishes admitted cascade changes after gate checks.",
            "cascade_abort": "Restores working rows to the base revision and closes the cascade.",
        },
        "command_metadata_standard": {
            "get_schema": "Machine-readable input schema for validation and adapter help.",
            "metadata": "Rich AI/documentation metadata: behavior, parameters, return values, examples, errors, best practices.",
            "required_metadata_fields": [
                "name",
                "version",
                "description",
                "category",
                "author",
                "email",
                "detailed_description",
                "parameters",
                "return_value",
                "usage_examples",
                "error_cases",
                "best_practices",
            ],
            "schema_rules": [
                "type=object",
                "properties list every public parameter",
                "required matches runtime requirements",
                "additionalProperties is explicit",
                "semantic validation lives in validate_params",
            ],
        },
    }
