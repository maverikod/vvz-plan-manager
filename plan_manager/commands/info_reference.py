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
            "plan_list": "Returns project_ids, project_count, and primary_project_id for each plan.",
            "step_get": "Returns top-level project_id.",
            "step_tree": "Returns project_id for every tree entry; include_content=true additionally returns fields, depends_on, and concepts without per-step reads.",
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


def prompt_chain_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for plan prompt-chain compilation."""
    return {
        "purpose": (
            "Read-only compilation of a committed, gate-green plan revision and "
            "scope into a deterministic prompt-chain corpus for downstream executors."
        ),
        "command": {
            "name": "plan_prompt_chain",
            "mutates": False,
            "queue_bound": True,
            "parameters": {
                "plan": "Plan name or UUID.",
                "revision": "Optional revision UUID; omit or pass 'head' for current head.",
                "scope": "whole_plan, G-NNN, or G-NNN/T-NNN.",
                "role": "coder, review, or conscience.",
                "include_statuses": "Defaults to frozen and ready_for_review.",
            },
        },
        "return_shape": {
            "waves": "Dependency waves as lists of G-NNN/T-NNN/A-NNN step keys.",
            "blocks": "Level-keyed block corpus: hrs, mrs, gs, ts, as, tool_instructions.",
            "assembly": "Per-step role-scoped manifest with use, wave, branch_path, and priority.",
            "meta": "dag_source, counts, include_statuses, and plan project bindings.",
        },
        "role_behavior": {
            "coder": "assembly.use contains only as and tool_instructions.",
            "review": "assembly.use may include upper-layer block selectors.",
            "conscience": "assembly.use may include upper-layer block selectors.",
        },
        "determinism": {
            "retrieval": "No retrieval or semantic search is performed.",
            "cache_key": "Every block has cache_key over canonical bytes.",
            "dag_source": "Waves derive from MRS relations plus target_file produce/consume edges, with explicit depends_on augmenting when present.",
        },
        "boundaries": [
            "No tokenization.",
            "No padding or provider cache markers.",
            "No standards injection.",
            "No model-tier selection.",
            "No prompt dispatch.",
            "No execution logging.",
        ],
        "domain_errors": {
            "PLAN_NOT_FOUND": "Plan identifier does not resolve.",
            "REVISION_NOT_FOUND": "Explicit revision is not the current head.",
            "INVALID_SCOPE": "Scope is not whole_plan, G-NNN, or G-NNN/T-NNN.",
            "INVALID_ROLE": "Role is not coder, review, or conscience.",
            "INVALID_STATUS_FILTER": "include_statuses is empty or unsupported.",
            "GATE_RED": "Mechanical gate is red; no partial payload is returned.",
            "CYCLE_DETECTED": "Derived DAG cannot be partitioned into waves.",
        },
    }


def step_lifecycle_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for step lifecycle transition APIs."""
    return {
        "purpose": (
            "Authoring lifecycle movement for GS/TS/AS steps. The authoritative "
            "state is step.status, not fields.status."
        ),
        "statuses": {
            "draft": "Editable authoring state.",
            "ready_for_review": "Prepared for review/freeze.",
            "frozen": "Published for prompt-chain/execution surfaces; content changes require cascade discipline.",
        },
        "commands": {
            "step_set_status": {
                "mutates": True,
                "scope": "single_step",
                "summary": "Backward-compatible single-step status transition command.",
            },
            "step_transition": {
                "mutates": True,
                "scope": "single_step_or_bulk_scope",
                "queue_bound": True,
                "summary": "Transition one step or whole_plan/G-NNN/G-NNN/T-NNN scope with dry_run, green-gate freeze checks, idempotent skips, and one revision per bulk write.",
            },
        },
        "bulk_scopes": ["whole_plan", "G-NNN", "G-NNN/T-NNN"],
        "freeze_behavior": {
            "require_green_default": True,
            "draft_to_frozen": "Allowed by step_transition as draft -> ready_for_review -> frozen inside one auditable batch revision.",
            "revision_count": "One version-store revision is produced for a non-empty bulk transition.",
        },
        "read_surfaces": {
            "step_get": "Returns authoritative status for one step.",
            "step_tree": "Returns authoritative status for every step; include_content and include_runtime are independent opt-in expansions.",
            "plan_prompt_chain": "Compiles only ready_for_review/frozen steps by default.",
        },
        "domain_errors": {
            "INVALID_SCOPE": "step_id/scope conflict or unsupported scope shape.",
            "INVALID_TRANSITION": "At least one selected step cannot legally move to the requested status.",
            "CASCADE_REQUIRED": "A frozen step would be reopened without cascade_uuid.",
            "CASCADE_CONFLICT": "cascade_uuid does not admit the mutation.",
            "GATE_RED": "Freezing was refused because the requested scope gate is red.",
        },
    }


def step_dependency_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the step dependency command family."""
    return {
        "purpose": (
            "Safe editing of a step's execution dependencies. depends_on is the "
            "real top-level graph column of a step, never fields.depends_on; "
            "these commands are the supported way to change it so plan_validate, "
            "graph_order, and graph_parallel_map see the new edges."
        ),
        "edge_model": {
            "direction": "current_step depends_on dependency_step: dependency_step runs before current_step.",
            "storage": "depends_on holds bare sibling step_ids; commands accept and return canonical paths.",
            "scope": (
                "Dependencies are sibling-scoped: same parent and level. Allowed "
                "shapes are GS->GS, TS->TS under one GS, and AS->AS under one TS. "
                "Cross-level or cross-parent references are refused with "
                "INVALID_DEPENDENCY_SCOPE; model cross-level ordering at the leaf "
                "(AS) level."
            ),
        },
        "commands": {
            "step_dependency_list": {
                "mutates": False,
                "summary": "List one step's depends_on and its dependents.",
            },
            "step_dependency_add": {
                "mutates": True,
                "summary": "Add one sibling dependency; idempotent (already_present) and cycle-safe.",
            },
            "step_dependency_remove": {
                "mutates": True,
                "summary": "Remove one dependency; idempotent (already_absent); tolerates stale ids.",
            },
            "step_dependency_set": {
                "mutates": True,
                "summary": "Replace the whole depends_on list; deduped, cycle-checked; returns old and new.",
            },
            "step_dependency_clear": {
                "mutates": True,
                "summary": "Clear all dependencies of a step.",
            },
            "step_dependency_preview": {
                "mutates": False,
                "summary": "Dry-run a batch of changes; report validity, cycle risk, and before/after order/waves.",
            },
            "step_dependency_apply": {
                "mutates": True,
                "summary": "Apply a batch all-or-nothing as one revision (dry_run default true).",
            },
        },
        "admission": (
            "Every mutation runs under the same regime as step_update: draft and "
            "ready_for_review steps are edited directly; a frozen step (or a step "
            "frozen at or below) requires an open cascade via cascade_uuid."
        ),
        "invariants": [
            "depends_on is a top-level step field; it is never written under fields.depends_on.",
            "A dependency must reference an existing sibling step (same parent and level).",
            "Self-dependencies and cycles are refused (SELF_DEPENDENCY, DEPENDENCY_CYCLE).",
            "add and remove are idempotent and do not duplicate or fail on repeats.",
            "A non-empty change set produces exactly one revision; step_dependency_apply is all-or-nothing.",
            "Every mutating command re-reads the step and returns its actual depends_on.",
        ],
        "domain_errors": {
            "STEP_NOT_FOUND": "The edited step reference does not resolve.",
            "AMBIGUOUS_STEP_ID": "A bare step id resolves to more than one step; use a canonical path.",
            "DEPENDENCY_STEP_NOT_FOUND": "The referenced dependency step does not resolve.",
            "SELF_DEPENDENCY": "A step was asked to depend on itself.",
            "INVALID_DEPENDENCY_SCOPE": "The dependency is not a sibling (different parent or level).",
            "DEPENDENCY_CYCLE": "The change would create a cycle in the dependency graph.",
            "CASCADE_REQUIRED": "A frozen target requires an open cascade.",
            "CASCADE_CONFLICT": "cascade_uuid does not match the plan's open cascade.",
            "FROZEN_ARTIFACT": "The target step or a descendant is frozen.",
        },
    }


def plan_lifecycle_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for plan deletion and catalog visibility."""
    return {
        "purpose": (
            "Plan-level removal and catalog visibility. A plan can be "
            "soft-deleted (hidden from the default catalog but preserved and "
            "reversible) or hard-deleted (removed permanently with all its "
            "artifacts). Soft-deletion state lives in plan.deleted_at."
        ),
        "plan_fields": {
            "deleted_at": (
                "Soft-deletion timestamp; null for a live plan, non-null "
                "when soft-deleted."
            ),
        },
        "commands": {
            "plan_delete": {
                "mutates": True,
                "modes": {
                    "soft": (
                        "Default (hard=false). Marks the plan deleted and "
                        "hides it from the default plan_list; the plan and "
                        "all artifacts are preserved and it stays resolvable "
                        "by uuid or name. Idempotent: repeating it reports "
                        "already_deleted=true without changing the original "
                        "deletion time."
                    ),
                    "hard": (
                        "hard=true. Permanently and irreversibly removes the "
                        "plan row and every child artifact (revisions, "
                        "paragraphs, concepts, relations, steps, node "
                        "versions, refs, cascades, step runtime, context "
                        "blocks) via ON DELETE CASCADE; applies whether or "
                        "not the plan was previously soft-deleted."
                    ),
                },
                "summary": (
                    "Soft- or hard-delete a plan resolved by uuid or name; "
                    "verifies the result by re-reading the plan row."
                ),
            },
            "plan_list": {
                "mutates": False,
                "summary": (
                    "Lists plans with their bound projects and a deleted "
                    "flag; soft-deleted plans are hidden unless "
                    "show_deleted=true."
                ),
            },
        },
        "read_surfaces": {
            "plan_list": (
                "Each row includes deleted (bool); pass show_deleted=true to "
                "include soft-deleted plans."
            ),
        },
        "invariants": [
            "Soft delete only hides a plan from the default catalog; every other command keeps operating on it unchanged.",
            "Soft delete is idempotent and never overwrites the original deletion time.",
            "A soft-deleted plan keeps its name reserved by the plan-name uniqueness constraint until it is hard-deleted.",
            "Hard delete is irreversible and cascades to every artifact belonging to the plan.",
        ],
        "domain_errors": {
            "PLAN_NOT_FOUND": "The plan identifier does not resolve; a soft-deleted plan still resolves and can be deleted again.",
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
            "human_owned_hrs": "source_spec.md is human-owned prose; procedures may label or mark non-binding text but never rewrite binding content on their own initiative. Targeted HRS text editing exists as paragraph-granular commands (para_insert / para_update / para_delete: insert, replace, or delete one binding paragraph addressed by label, admission-guarded and snapshot-recorded) and executes only human-decided changes.",
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
            "target_file_lock": "Same-file AS under one TS are serialized by priority. Cross-branch writers derive order from declared TS/GS dependencies; ambiguous pairs fail dependencies.same_file_order. Runtime file locking remains a second barrier; independent files may run in parallel.",
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


def todo_work_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the TODO work-item command family."""
    return {
        "purpose": (
            "Runtime TODO work items (C-005): anchored, kinded work records "
            "with a nice-scale priority, typed links to other TODOs, a "
            "surfacing queue, and a promotion path into a normative cascade "
            "request. TODOs are runtime overlay state, never frozen plan "
            "truth."
        ),
        "kinds": [
            "task", "followup", "cleanup", "question", "risk", "investigation",
            "review", "update", "migration", "rebuild", "test_rerun", "documentation",
        ],
        "statuses": ["open", "ready", "in_progress", "blocked", "resolved", "closed", "cancelled"],
        "priority_nice": {
            "range": "-20 (highest) to 19 (background), following the Linux nice principle.",
            "tie_break_order": (
                "priority_nice, has_blocker, deps_ready, age (older first), "
                "due_at (earlier first, unset sorts last), kind_rank, execution_wave."
            ),
        },
        "primary_anchor_types": [
            "none", "project", "file", "plan", "revision", "step",
            "execution_attempt", "review_result", "bug", "bug_fix", "todo",
        ],
        "link_types": [
            "relates_to", "blocks", "blocked_by", "duplicates", "caused_by",
            "created_from", "requires", "followup_for",
        ],
        "commands": {
            "todo_create": {
                "mutates": True,
                "summary": "Create a new TODO with a title, description, kind, priority_nice, and a primary anchor.",
            },
            "todo_get": {
                "mutates": False,
                "summary": "Return one TodoItem by uuid.",
            },
            "todo_list": {
                "mutates": False,
                "summary": "List TodoItems with shared runtime filters (project, status, kind, priority, assignee, ...) and pagination.",
            },
            "todo_update": {
                "mutates": True,
                "summary": "Update mutable TodoItem fields (status, assigned_to, priority_nice, due_at, blocking_reason, execution_result, ...).",
            },
            "todo_resolve": {
                "mutates": True,
                "summary": "Transition a TodoItem to resolved and record resolved_at/execution_result.",
            },
            "todo_close": {
                "mutates": True,
                "summary": "Transition a TodoItem to closed (or cancelled) as a terminal state.",
            },
            "todo_link_add": {
                "mutates": True,
                "summary": "Create a typed link between two TODOs; guards self-reference, duplicates, and blocking cycles (blocks/blocked_by).",
            },
            "todo_link_remove": {
                "mutates": True,
                "summary": "Remove an existing TODO link by link_uuid.",
            },
            "todo_queue": {
                "mutates": False,
                "summary": "Surface the TODO-derived slice of the unified runtime work queue, filtered by resource availability (models, runtime, vast, locked files/projects).",
            },
            "todo_promote_to_cascade_request": {
                "mutates": True,
                "summary": "Promote an existing TODO into a CascadeRequest targeting a frozen-truth artifact level (HRS/MRS/GS/TS/AS); does not itself open or commit a cascade.",
            },
        },
        "guard_error_attribution": (
            "todo_link_add's underlying store (todo_link_store.create_todo_link) routes "
            "duplicate-active-link and blocking-cycle guard violations through the typed "
            "DuplicateLinkError/LinkCycleError subclasses of RuntimeValidationError "
            "(plan_manager.domain.runtime_integrity), which map_exception attributes to the "
            "specific DUPLICATE_LINK / LINK_CYCLE domain codes. The remaining guards (invalid "
            "link_type, self-reference, missing todo) have no dedicated exception subclass "
            "and still fall through to the generic RUNTIME_VALIDATION_ERROR domain code."
        ),
        "invariants": [
            "A TODO's authoritative state is TodoItem.status, one of the seven TODO_STATUSES.",
            "priority_nice must lie in the closed range [-20, 19]; validated by validate_nice_priority.",
            "A TODO link may not reference the same TODO as both source and target (self-reference).",
            "Blocking edges (blocks/blocked_by) must not form a cycle across all active links.",
            "todo_queue reasons only about the runtime work queue; it never reads or alters the frozen plan's depends_on graph.",
            "todo_promote_to_cascade_request creates a CascadeRequest record; opening/admitting/committing the cascade itself follows the separate cascade discipline.",
        ],
        "domain_errors": {
            "TODO_NOT_FOUND": "The supplied todo identifier does not resolve to an existing TODO item.",
            "TODO_LINK_NOT_FOUND": "The supplied todo link identifier does not resolve to an existing link.",
            "INVALID_ANCHOR": "The supplied primary anchor is malformed, uses an unsupported anchor_type, or does not reference an existing anchor target (anchor target lookup misses also surface as INVALID_ANCHOR or RUNTIME_VALIDATION_ERROR; no separate ANCHOR_NOT_FOUND code exists).",
            "INVALID_NICE_PRIORITY": "The supplied priority_nice value is outside the valid range [-20, 19].",
            "DUPLICATE_LINK": "An active link with the same (from_todo, to_todo, link_type) triple already exists; raised by todo_link_add via the typed DuplicateLinkError guard.",
            "LINK_CYCLE": "The requested blocking link (blocks/blocked_by) would introduce a cycle in the blocking-link graph; raised by todo_link_add via the typed LinkCycleError guard.",
        },
    }


def runtime_comment_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the runtime comment command family."""
    return {
        "purpose": (
            "Runtime comments (C-014): append-oriented, immutable notes attached "
            "to one of eleven anchor target kinds. Editing a comment creates a "
            "new record that supersedes the old one; history is never lost. A "
            "comment is always a separate persisted entity, never a field of "
            "another object."
        ),
        "kinds": [
            "comment", "observation", "warning", "blocker", "decision", "review",
            "question", "answer", "evidence", "escalation", "execution_note", "verification_note",
        ],
        "anchor_types": [
            "plan", "revision", "step", "project", "file", "todo", "bug", "bug_fix",
            "execution_attempt", "review_result", "escalation",
        ],
        "visibility_modes": {
            "audit_only": "Enters no prompt context; excluded from every execution/owner/reviewer/public assembly.",
            "execution_context": "Enters the execution prompt context only.",
            "owner_context": "Enters the owner prompt context only.",
            "reviewer_context": "Enters the reviewer prompt context only.",
            "public_summary": "Enters every prompt context: execution, owner, reviewer, and public.",
        },
        "commands": {
            "comment_add": {
                "mutates": True,
                "summary": "Create a new RuntimeComment with a kind, visibility, anchor, and body.",
            },
            "comment_get": {
                "mutates": False,
                "summary": "Return one RuntimeComment by comment_uuid.",
            },
            "comment_list": {
                "mutates": False,
                "summary": "List RuntimeComments with shared runtime filters and pagination.",
            },
            "comment_resolve": {
                "mutates": True,
                "summary": "Mark a RuntimeComment resolved (for kinds that track a resolved boolean, e.g. blocker, question).",
            },
            "comment_supersede": {
                "mutates": True,
                "summary": "Create a new comment record referencing supersedes_comment_uuid; the prior record is preserved unchanged.",
            },
        },
        "invariants": [
            "A comment always attaches to a subject; 'none' is not a valid comment anchor type (unlike PrimaryAnchor's 'none').",
            "Supersession is additive: superseding a comment never mutates or deletes the superseded record.",
            "may_reach_context(visibility, context_kind) is the single predicate governing whether a comment enters a given prompt context; is_executor_reachable is the execution-context convenience form.",
            "audit_only comments are excluded from every prompt context, including execution, by construction.",
        ],
        "domain_errors": {
            "COMMENT_NOT_FOUND": "The supplied comment identifier does not resolve to an existing, non-deleted RuntimeComment record.",
            "INVALID_VISIBILITY": "The supplied comment visibility value is not one of the five known CommentVisibility modes.",
            "INVALID_ANCHOR": "The supplied comment anchor is malformed, uses an anchor_type outside the eleven-kind comment anchor vocabulary (or 'none', which comments reject), or does not reference an existing anchor target.",
        },
    }


def execution_attempt_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the execution attempt command family."""
    return {
        "purpose": (
            "Execution attempts (C-016): the per-run record of one real "
            "execution against a step, TODO, or bug fix. An execution attempt "
            "is a factual log of what happened; it is never itself a "
            "correctness certificate — certification is the separate job of "
            "review_result under the owner review ladder."
        ),
        "statuses": [
            "queued", "running", "succeeded", "failed", "cancelled",
            "timed_out", "needs_review", "needs_escalation",
        ],
        "terminal_statuses": ["succeeded", "failed", "cancelled", "timed_out"],
        "commands": {
            "execution_attempt_create": {
                "mutates": True,
                "summary": "Create a new ExecutionAttempt for a step (optionally scoped to a plan revision, TODO, or bug fix), recording the assigned model binding/provider/model.",
            },
            "execution_attempt_get": {
                "mutates": False,
                "summary": "Return one ExecutionAttempt by attempt_uuid.",
            },
            "execution_attempt_list": {
                "mutates": False,
                "summary": "List ExecutionAttempts with shared runtime filters (project, plan, step, status, model, ...) and pagination.",
            },
            "execution_attempt_report": {
                "mutates": True,
                "summary": "Report the outcome of a running attempt: status, result_summary, changed_files, command_test_results, resource_accounting, error, or escalation_reason.",
            },
        },
        "record_fields": {
            "parent_attempt_uuid": "Optional link to a prior attempt this one retries or follows.",
            "input_context_hash": "Hash of the compiled input context the attempt was run against.",
            "used_provider_used_model": "Actual provider/model used, which may differ from assigned_provider/assigned_model (e.g. after a fallback).",
        },
        "invariants": [
            "is_terminal_status(status) is true only for succeeded, failed, cancelled, or timed_out.",
            "An execution attempt never certifies its own correctness; review_result and the owner review ladder are the certification path.",
        ],
        "domain_errors": {
            "EXECUTION_ATTEMPT_NOT_FOUND": "The supplied execution attempt identifier does not resolve to a stored execution_attempt record.",
            "INVALID_ANCHOR": "The supplied plan/revision/step anchor is malformed, or the step does not belong to the given plan (and revision, if given).",
        },
    }


def review_escalation_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the review-result and escalation command families."""
    return {
        "purpose": (
            "Review results (C-018) record the outcome of reviewing an "
            "execution attempt or a plan revision. Escalations (C-037) raise "
            "a decision to the next-level owner. Both are governed by the "
            "owner review ladder (C-017), which enforces no self-certification "
            "and routes escalation strictly upward: hrs_mrs verifies gs; gs "
            "verifies ts; ts verifies as AND as_execution. The code executor "
            "that produces as_execution is never itself an ownership level and "
            "may never certify its own result."
        ),
        "ladder_levels": ["hrs_mrs", "gs", "ts", "as"],
        "verification_map": {
            "gs": "verified by hrs_mrs",
            "ts": "verified by gs",
            "as": "verified by ts",
            "as_execution": "verified by ts (produced by code_execution, a non-ownership-level producer)",
        },
        "review_object_types": ["execution_attempt", "revision"],
        "review_statuses": ["accepted", "rejected", "changes_requested", "escalated", "needs_owner_decision"],
        "escalation_statuses": ["open", "resolved"],
        "commands": {
            "review_result_create": {
                "mutates": True,
                "summary": "Record a ReviewResult for an execution attempt or revision, with findings, evidence, verification_commands, and an optional escalation_target_uuid.",
            },
            "review_result_get": {
                "mutates": False,
                "summary": "Return one ReviewResult by review_uuid.",
            },
            "review_result_list": {
                "mutates": False,
                "summary": "List ReviewResults with shared runtime filters and pagination.",
            },
            "escalation_create": {
                "mutates": True,
                "summary": "Create a new Escalation anchored to the entity in question, with a reason, from_level, and to_level.",
            },
            "escalation_resolve": {
                "mutates": True,
                "summary": "Resolve an open Escalation, recording resolution, resolved_by, and resolved_at.",
            },
        },
        "self_certification_guard": (
            "guard_no_self_certification(reviewer_level, produced_level) raises when the "
            "reviewer level equals producer_of(produced_level); review_result_create enforces "
            "this so a reviewer identity equal to the execution attempt's producer identity "
            "(created_by) is refused."
        ),
        "invariants": [
            "verifier_of/producer_of/subordinate_levels/escalation_target are all pure lookups over LADDER_LEVELS and VERIFICATION_MAP; escalation_target returns None only for the most senior level (hrs_mrs).",
            "guard_valid_reviewer refuses a review recorded by any level other than the expected verifier of the produced level.",
        ],
        "domain_errors": {
            "REVIEW_RESULT_NOT_FOUND": "The requested review result does not resolve.",
            "ESCALATION_NOT_FOUND": "The requested escalation does not resolve.",
            "SELF_CERTIFICATION_FORBIDDEN": "The reviewer identity equals the producer identity of the execution attempt under review; the code executor may not certify its own result.",
            "INVALID_RUNTIME_STATUS_TRANSITION": "The requested status value is not a valid status for this entity.",
            "INVALID_ANCHOR": "The supplied primary anchor is malformed or does not reference an existing anchor target.",
        },
    }


def model_binding_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the model binding command family."""
    return {
        "purpose": (
            "Model bindings (C-009) configure which provider/model serves a "
            "runtime role at a given scope. Six scopes form a strict "
            "specificity order (C-010); resolution (C-012) selects the single "
            "most-specific applicable binding for a (step, role) target and "
            "reports the full inheritance path as provenance."
        ),
        "scopes_by_specificity": ["system", "plan", "level", "branch", "step", "role"],
        "spec_levels": ["HRS", "MRS", "GS", "TS", "AS"],
        "runtime_roles": [
            "hrs_author", "mrs_author", "gs_author", "ts_author", "as_author",
            "code_executor", "owner_reviewer", "conscience_reviewer",
            "escalation_owner", "bug_investigator", "bug_fixer", "verification_executor",
        ],
        "scope_field_requirements": {
            "system": "No plan_uuid, spec_level, branch_step_uuid, or step_uuid.",
            "plan": "Requires plan_uuid; no spec_level, branch_step_uuid, or step_uuid.",
            "level": "Requires plan_uuid and spec_level (one of HRS/MRS/GS/TS/AS); no branch_step_uuid or step_uuid.",
            "branch": "Requires plan_uuid and branch_step_uuid; no spec_level or step_uuid.",
            "step": "Requires plan_uuid and step_uuid; no spec_level or branch_step_uuid.",
            "role": "Requires role; no spec_level, branch_step_uuid, or step_uuid.",
        },
        "commands": {
            "model_binding_set": {
                "mutates": True,
                "summary": "Create or update a ModelBinding at a given scope, with provider/model, optional fallback, max_retries, timeout, and context_budget.",
            },
            "model_binding_get": {
                "mutates": False,
                "summary": "Return one ModelBinding by binding_uuid.",
            },
            "model_binding_list": {
                "mutates": False,
                "summary": "List ModelBindings with shared runtime filters and pagination.",
            },
            "model_binding_remove": {
                "mutates": True,
                "summary": "Soft-remove (deactivate/delete) a ModelBinding by binding_uuid.",
            },
            "model_binding_resolve": {
                "mutates": False,
                "summary": "Resolve the effective binding for a (role, plan_uuid?, spec_level?, branch_step_uuid?, step_uuid?) target, returning effective_provider/model and the ranked inheritance_path.",
            },
        },
        "resolution_rules": {
            "applicability": "binding_applies filters to active, non-deleted bindings whose role is None or matches the target role, and whose scope-specific identifiers match the target.",
            "winner_selection": "Applicable bindings are sorted by scope_rank (ascending specificity), then role-specificity, then plan-specificity, then created_at, then binding_uuid; the last (most specific) entry wins.",
            "no_match": "resolve_effective_binding raises ModelResolutionError (a RuntimeValidationError) when no binding applies to the target.",
        },
        "invariants": [
            "scope_rank/is_more_specific/order_by_specificity/most_specific all derive from the single fixed INHERITANCE_ORDER tuple (system, plan, level, branch, step, role).",
            "validate_scope_fields enforces that only the fields a scope requires are populated for that scope.",
        ],
        "domain_errors": {
            "MODEL_BINDING_NOT_FOUND": "The supplied binding identifier does not resolve to a stored model_binding record.",
            "INVALID_BINDING_SCOPE": "The supplied scope value, or the fields required by that scope, are inconsistent with the six-level model-binding inheritance scope vocabulary.",
            "INVALID_RUNTIME_ROLE": "The supplied role value is not one of the twelve recognized runtime roles.",
        },
    }


def bug_lifecycle_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the bug report/impact/fix/propagation command family."""
    return {
        "purpose": (
            "The bug lifecycle (C-020..C-026) tracks a discovered defect from "
            "report through source fix to full downstream resolution. A bug "
            "has exactly one primary source anchor (BugSource, C-021) but many "
            "impact records (BugImpact, C-022) describing what it affects; a "
            "fix (BugFix, C-024) targets the source, and propagations "
            "(BugFixPropagation, C-025) track the required downstream action "
            "per impact. Fixing the source does not automatically fix "
            "dependent projects. Closure discipline (C-026) refuses bug_close "
            "until the source fix is verified and every impact/propagation is "
            "fully handled or explicitly, ownerly skipped."
        ),
        "bug_statuses": [
            "reported", "triaged", "confirmed", "rejected", "duplicate", "fixing",
            "fixed_source", "propagating", "verified", "closed", "reopened",
        ],
        "bug_kinds": [
            "functional", "wrong_output", "data_loss", "regression", "compatibility",
            "stale_context", "planning", "performance", "security", "infrastructure",
            "deployment", "configuration", "documentation", "user_experience",
        ],
        "bug_severities": ["blocker", "critical", "major", "minor", "trivial"],
        "bug_source_types": [
            "project", "file", "plan", "revision", "step", "command",
            "runtime_service", "execution_attempt", "unidentified",
        ],
        "bug_impact_target_types": [
            "project", "file", "plan", "revision", "step", "command",
            "runtime_service", "container_image", "deployment", "dependency", "documentation",
        ],
        "bug_impact_statuses": ["suspected", "confirmed", "unaffected", "pending_resolution", "resolved", "verified", "skipped"],
        "bug_fix_types": [
            "code", "configuration", "migration", "data", "dependency_update",
            "documentation", "test", "workaround", "deployment", "plan_cascade",
        ],
        "bug_fix_statuses": ["proposed", "in_progress", "implemented", "failed", "partial", "reverted", "rejected", "verified"],
        "propagation_actions": [
            "pull_dependency", "update_dependency_version", "bump_version", "rebuild_package",
            "rebuild_image", "redeploy", "rerun_tests", "update_generated_code",
            "update_configuration", "run_migration", "update_documentation",
            "create_plan_cascade", "no_action_required",
        ],
        "propagation_statuses": ["pending", "ready", "in_progress", "done", "failed", "blocked", "skipped", "verified"],
        "commands": {
            "bug_create": {"mutates": True, "summary": "Create a BugReport with a source anchor, kind, severity, and priority_nice."},
            "bug_get": {"mutates": False, "summary": "Return one BugReport by bug_uuid."},
            "bug_list": {"mutates": False, "summary": "List BugReports with shared runtime filters and pagination."},
            "bug_update": {"mutates": True, "summary": "Update mutable BugReport fields (owner, severity, priority_nice, descriptions, ...)."},
            "bug_confirm": {"mutates": True, "summary": "Transition a bug to confirmed and record confirmed_at."},
            "bug_reject": {"mutates": True, "summary": "Transition a bug to rejected."},
            "bug_mark_duplicate": {"mutates": True, "summary": "Transition a bug to duplicate and record duplicate_of_uuid."},
            "bug_reopen": {"mutates": True, "summary": "Transition a closed/verified bug to reopened and record reopened_at; preserves history rather than deleting it."},
            "bug_close": {"mutates": True, "summary": "Transition a bug to closed; refused (guard_close/evaluate_closure) unless BugClosureDiscipline is satisfied."},
            "bug_impact_add": {"mutates": True, "summary": "Add a BugImpact target (project/file/plan/revision/step/command/runtime_service/container_image/deployment/dependency/documentation) with an impact_type and status."},
            "bug_impact_discover": {"mutates": True, "summary": "Auto-discover candidate BugImpact targets, e.g. via the project dependency graph's suspected_impact_targets."},
            "bug_impact_list": {"mutates": False, "summary": "List BugImpacts for a bug with shared runtime filters and pagination."},
            "bug_impact_update": {"mutates": True, "summary": "Update a BugImpact's status (skipped transitions require a non-empty reason and skip_decided_by)."},
            "bug_fix_create": {"mutates": True, "summary": "Create a BugFix attempt for a bug's source, with fix_type and summary."},
            "bug_fix_list": {"mutates": False, "summary": "List BugFixes for a bug with shared runtime filters and pagination."},
            "bug_fix_update": {"mutates": True, "summary": "Update a BugFix's status and implementation detail fields."},
            "bug_fix_verify": {"mutates": True, "summary": "Record verification of a BugFix (verification_method, expected/actual_result, passed) and set verified_at."},
            "bug_propagation_create": {"mutates": True, "summary": "Create a BugFixPropagation for one impact, with a propagation action and status."},
            "bug_propagation_list": {"mutates": False, "summary": "List BugFixPropagations with shared runtime filters and pagination."},
            "bug_propagation_update": {"mutates": True, "summary": "Update a BugFixPropagation's status, evidence, or verification_result."},
            "bug_propagation_generate_todos": {"mutates": True, "summary": "Generate TODO work items from open propagations so they surface on the unified runtime work queue."},
        },
        "closure_discipline": {
            "blocking_conditions": [
                "source fix not verified",
                "an impact is in an open status (suspected, confirmed, pending_resolution, resolved) rather than a cleared one (unaffected, verified)",
                "a skipped impact is missing an explicit reason and an owner decision (skip_decided_by)",
                "a propagation is not in a finished status (done, verified, skipped)",
                "mandatory linked TODOs are not closed",
                "required plan cascades are not finished",
            ],
            "status_after_source_fix": "fixed_source when no open downstream remains, else propagating.",
            "reopen": "Re-discovery reopens a closed/verified bug into reopened without destroying prior fix/impact/propagation history.",
        },
        "invariants": [
            "A bug has exactly one BugSource (its single primary origin) but any number of BugImpact records (what it affects).",
            "Fixing the source does not automatically resolve dependent-project impacts; each requires its own propagation.",
            "bug_close is refused unless evaluate_closure(...).can_close is True; the returned blocking_reasons enumerate every unmet condition.",
        ],
        "domain_errors": {
            "BUG_NOT_FOUND": "The supplied bug identifier does not resolve to a stored BugReport.",
            "BUG_IMPACT_NOT_FOUND": "The supplied impact_uuid does not resolve to a stored bug_impact record.",
            "BUG_FIX_NOT_FOUND": "The supplied bug fix identifier does not resolve to an existing BugFix record.",
            "BUG_PROPAGATION_NOT_FOUND": "The supplied propagation identifier does not resolve to a stored bug fix propagation record.",
            "INVALID_ANCHOR": "The supplied primary source anchor for the bug is malformed, incomplete for its source_type, or does not reference an existing anchor target.",
            "INVALID_RUNTIME_STATUS_TRANSITION": "The requested status transition is not permitted for the target entity (bug, bug impact, bug fix, or propagation), including bug_close being refused under BugClosureDiscipline.",
        },
    }


def project_dependency_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the project dependency graph command family."""
    return {
        "purpose": (
            "Project dependency edges (C-023) form a typed, directed graph "
            "over external analysis-server project UUIDs (C-032). Reverse "
            "traversal of this graph (suspected_impact_targets) yields the "
            "candidate impact set used by bug_impact_discover."
        ),
        "dependency_types": [
            "library", "runtime_adapter", "api_contract", "protocol", "generated_code",
            "container_base", "deployment_base", "shared_schema", "tooling", "test_dependency",
        ],
        "discovery_sources": [
            "manual", "project_metadata", "packaging", "imports",
            "container_manifest", "runtime_registration", "code_analysis_server",
        ],
        "confidence_levels": ["confirmed", "unconfirmed", "suspected"],
        "commands": {
            "project_dependency_add": {
                "mutates": True,
                "summary": "Add a directed dependency edge (dependent_project_id depends_on depends_on_project_id) with a type, discovery_source, and confidence; cycle-checked.",
            },
            "project_dependency_remove": {
                "mutates": True,
                "summary": "Remove (soft-delete) a dependency edge by dependency_uuid.",
            },
            "project_dependency_list": {
                "mutates": False,
                "summary": "List ProjectDependency edges with shared runtime filters and pagination.",
            },
            "project_dependency_discover": {
                "mutates": True,
                "summary": "Auto-discover candidate dependency edges from a non-manual discovery_source; such edges may not be silently confirmed.",
            },
            "project_dependents": {
                "mutates": False,
                "summary": "Return the set of projects that transitively depend on a given project, via suspected_impact_targets reverse traversal.",
            },
            "project_view": {
                "mutates": False,
                "summary": "Project-centric aggregate view: paginated todos/bugs (plus a comments count) scoped to one project, direct or transitive via bound plans, built by calling todo_list/bug_list/comment_list's own store functions -- never a separate query shape.",
            },
        },
        "guards": {
            "self_reference": "validate_dependency_project_ids refuses dependent_project_id == depends_on_project_id.",
            "external_id_validity": "Both endpoints must be well-formed external project UUID references (is_valid_external_project_id); no local project catalog is consulted or maintained.",
            "silent_auto_confirm": "guard_discovery_not_silently_confirmed refuses confidence=confirmed when discovery_source is not manual.",
            "cycle": "guard_no_dependency_cycle (detect_cycle) refuses an edge that would create a directed cycle in the dependency graph.",
        },
        "invariants": [
            "planmgr stores only opaque external project UUID references (C-032); it never owns or looks up a local project catalog or row.",
            "suspected_impact_targets walks the reverse-edge graph outward from a source project id and returns every transitively dependent project, excluding the origin itself.",
        ],
        "domain_errors": {
            "PROJECT_DEPENDENCY_NOT_FOUND": "The supplied dependency_uuid does not resolve to an existing project_dependency edge.",
            "PROJECT_DEPENDENCY_CYCLE": "Creating this edge would introduce a directed cycle in the project dependency graph.",
            "DUPLICATE_PROJECT_DEPENDENCY": "An active edge already exists for this (dependent_project_id, depends_on_project_id, dependency_type) combination.",
            "INVALID_PROJECT_ID": "The supplied project identifier is not a valid external analysis-server project reference.",
        },
    }


def runtime_filtering_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the shared runtime listing filter and pagination surface (C-030)."""
    return {
        "purpose": (
            "A uniform filter and pagination vocabulary shared across every "
            "runtime-listing command (todo_list, comment_list, "
            "execution_attempt_list, review_result_list, model_binding_list, "
            "bug_list, bug_impact_list, bug_fix_list, bug_propagation_list, "
            "project_dependency_list). Each list command declares only the "
            "subset of canonical filter fields that apply to its entity."
        ),
        "filter_fields": [
            "project", "file", "anchor_plan", "revision", "step", "status", "kind",
            "severity", "priority", "owner", "assignee", "model",
            "created_after", "created_before", "active_only", "unanchored_only",
            "unresolved_impacts", "unverified_fixes",
        ],
        "pagination_fields": {
            "limit": "Maximum results to return; default 50, clamped to [1, 200].",
            "offset": "Results to skip; default 0, must be >= 0.",
        },
        "validation": {
            "uuid_fields": "project, anchor_plan, revision, step must be valid UUID strings.",
            "date_time_fields": "created_after, created_before must be ISO-8601 timestamp strings.",
            "priority": "Must be an integer in [-20, 19] when the field name is 'priority'.",
            "boolean_fields": "active_only, unanchored_only, unresolved_impacts, unverified_fixes must be booleans.",
        },
        "helpers": {
            "filter_schema_properties": "Builds the JSON-schema properties fragment for a command's declared filter fields.",
            "filter_metadata_params": "Builds the metadata parameters fragment for a command's declared filter fields.",
            "pagination_schema_properties": "Builds the JSON-schema properties fragment for limit/offset.",
            "pagination_metadata_params": "Builds the metadata parameters fragment for limit/offset.",
            "parse_filters": "Parses and validates provided filter values against a command's declared field subset; raises INVALID_FILTER on any per-field validation failure.",
            "parse_pagination": "Parses and clamps limit/offset; raises INVALID_PAGINATION when a supplied value is not an integer, offset is negative, or limit is less than 1.",
        },
        "related_status_filter": (
            "plan_prompt_chain's include_statuses parameter is a separate, "
            "narrower status-filter surface (not part of runtime_filtering) "
            "that raises INVALID_STATUS_FILTER when empty or unsupported; see "
            "the prompt_chain capability entry."
        ),
        "domain_errors": {
            "INVALID_FILTER": "A provided runtime-listing filter value failed validation for its declared field (wrong type, malformed UUID/timestamp, or out-of-range priority).",
            "INVALID_PAGINATION": "A provided limit or offset value is not an integer, offset is negative, or limit is less than 1.",
        },
    }


def overlay_capabilities() -> dict[str, Any]:
    """Return machine-readable notes for the runtime overlay export/import round trip (C-034)."""
    return {
        "purpose": (
            "The runtime overlay snapshot (C-034) is a read-only, serializable "
            "document assembling every runtime overlay store's current state "
            "for one plan into one payload: TODOs, TODO links, model "
            "bindings, runtime comments, execution attempts, review results, "
            "escalations, bug reports, bug impacts, bug fixes, bug fix "
            "propagations, project dependencies, the runtime audit log, and "
            "cascade requests. It is deliberately separate from the "
            "normative plan_export/plan_import surface and must never be "
            "conflated with it."
        ),
        "sections": [
            "todo_items", "todo_links", "model_bindings", "runtime_comments",
            "execution_attempts", "review_results", "escalations", "bug_reports",
            "bug_impacts", "project_dependencies", "bug_fixes", "bug_fix_propagations",
            "runtime_audit_log", "cascade_requests",
        ],
        "functions": {
            "export_runtime_overlay": {
                "mutates": False,
                "summary": (
                    "Assemble a RuntimeOverlaySnapshot for one plan_uuid by reading each "
                    "overlay store's list_* function with include_deleted=True where the "
                    "store supports it; plan-scoped sections (model_bindings, "
                    "runtime_comments, execution_attempts, runtime_audit_log, "
                    "cascade_requests) are filtered to plan_uuid, the rest are read in full."
                ),
            },
            "RuntimeOverlaySnapshot.to_payload / from_payload": {
                "mutates": False,
                "summary": "Symmetric serialization: every section round-trips through to_payload/from_payload without loss.",
            },
            "import_runtime_overlay": {
                "mutates": True,
                "summary": (
                    "Re-create runtime overlay records from a RuntimeOverlaySnapshot via "
                    "each store's create_* function, remapping cross-referenced runtime "
                    "UUIDs (e.g. anchor_ref_id, source_ref_id) to the freshly assigned "
                    "identities as records are recreated; never mutates frozen plan truth."
                ),
            },
        },
        "include_deleted_semantics": {
            "twelve_soft_deletable_stores": "todo_items, todo_links, model_bindings, runtime_comments, execution_attempts, review_results, escalations, bug_reports, bug_impacts, project_dependencies, bug_fixes, bug_fix_propagations are all read with include_deleted=True so the snapshot captures soft-deleted rows too.",
            "runtime_audit_log": "Append-only; defines no include_deleted parameter because soft deletion is itself an appended action, never a removed row.",
            "cascade_requests": "Defines no include_deleted parameter; read by plan_uuid only.",
        },
        "invariants": [
            "export_runtime_overlay performs read (SELECT) operations only; it never writes.",
            "This module is deliberately separate from plan_manager.exchange.exporter (the normative plan export) and must never import it.",
            "Overlay import remaps cross-referenced runtime UUIDs as fresh identities are assigned, so re-imported records do not collide with or silently alias existing rows.",
        ],
        "domain_errors": {
            "RUNTIME_VALIDATION_ERROR": "A record in the snapshot fails a shared runtime validation check during import (e.g. malformed anchor, invalid enum value).",
        },
    }


def runtime_write_invariants() -> dict[str, Any]:
    """Return machine-readable notes for the shared runtime write guards common to every runtime overlay command (C-002, C-031)."""
    return {
        "purpose": (
            "Shared validation and mutation-boundary primitives (C-031) used "
            "by every runtime overlay domain module: UUID validation, "
            "priority_nice range validation, anchor/step membership checks, "
            "generic cycle detection, generic duplicate-link protection, and "
            "the frozen-truth mutation guard (C-002) that keeps the runtime "
            "API from ever writing to plan/revision/step/concept/relation/"
            "paragraph/node_version/ref."
        ),
        "frozen_truth_tables": [
            "plan", "revision", "step", "concept", "relation", "paragraph", "node_version", "ref",
        ],
        "shared_primitives": {
            "guard_frozen_truth": "Raises FrozenTruthMutationError if a candidate write target is one of the eight frozen-truth tables.",
            "validate_uuid": "Accepts a uuid.UUID or a UUID-parseable string; raises RuntimeValidationError otherwise.",
            "validate_priority_nice": "Accepts an int in [-20, 19]; raises RuntimeValidationError otherwise.",
            "check_row_exists": "Existence check against a caller-supplied table allowlist, mirroring the identity.py allowlist discipline so no unvalidated table name reaches SQL interpolation.",
            "validate_step_in_plan_revision": "Validates a step belongs to a plan and, if a revision is given, to that revision's reconstructed state.",
            "validate_file_reference": "Structural-only check that a file_path is project-relative with no '..' segments; performs no filesystem or catalog lookup.",
            "detect_cycle": "Generic directed-graph DFS cycle detector; shared by TODO blocking-link cycles and project-dependency cycles alike.",
            "ensure_no_duplicate": "Generic tuple-membership duplicate guard; shared by TODO link duplication.",
            "verify_inheritance_chain": "Generic subsequence-order verifier; used to check a level chain against a caller-supplied allowed_order.",
        },
        "invariants": [
            "The runtime API must never mutate frozen plan truth (C-002); guard_frozen_truth is the single enforcement point for that guarantee across every runtime store.",
            "Every runtime domain module raises RuntimeValidationError (or the FrozenTruthMutationError subclass) for its own guard violations; commands map these via map_exception into stable DOMAIN_CODES.",
            "RuntimeValidationError is deliberately generic: several distinct guards in the same module (e.g. todo link self-reference, duplication, cycle) currently share one exception type and therefore one mapped domain code, RUNTIME_VALIDATION_ERROR, rather than a dedicated code per guard.",
        ],
        "domain_errors": {
            "RUNTIME_VALIDATION_ERROR": "A runtime write failed a shared or module-specific RuntimeValidationError guard; the message carries the specific reason.",
            "FROZEN_TRUTH_WRITE": "A runtime command attempted to write to a frozen-truth table (plan, revision, step, concept, relation, paragraph, node_version, or ref).",
            "INVALID_RUNTIME_STATUS_TRANSITION": "A requested status value is not a legal value or transition for the target runtime entity's status vocabulary.",
        },
    }
