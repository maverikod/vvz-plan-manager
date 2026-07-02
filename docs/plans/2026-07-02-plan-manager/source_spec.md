<!-- non-binding -->
# Plan Manager — Source Specification (HRS)

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com

Status: draft HRS for the plan `2026-07-02-plan-manager`. Supersedes the plan
`2026-05-07-plan-manager-mcp-api` (buffer model and own vectorization are
abandoned). This document follows `plan_standard_machine.yaml` level 1
(source_spec): every binding paragraph starts with a stable `{xxxx}` label;
paragraphs inside non-binding blocks are excluded from concept extraction.

Platform facts referenced below were verified against mcp_proxy_adapter
8.10.15 sources and its reference consumer (code_analysis / casmgr).
<!-- /non-binding -->

## 1. Purpose and boundaries

{k2p7} Plan Manager is a standalone MCP server that manages software development plans structured as the five-level hierarchy HRS -> MRS -> GS -> TS -> AS defined by `plan_standard_machine.yaml`. It owns storage, navigation, mutation, lifecycle, and verification of plan artifacts.

{m9x4} The primary product of the server is a verification mechanism used *during* plan authoring. It consists of two strictly separated layers: a deterministic mechanical gate (binary: fix-here or pass) and a semantic completeness measurement (a normalized numeric index). Mechanical findings are never averaged into the semantic index: a branch with one broken reference is a broken branch, not a lowered score.

{q1w8} The server is self-contained. It must not depend on any other MCP server for its core function. The single optional external integration is an embedding service reached through a URL taken from configuration. When the embedding service is unavailable, every function except semantic scoring keeps working, and scoring returns an explicit low-trust verdict instead of failing.

{r5t2} Coverage matrices are not stored. Every coverage, inventory, and graph view is computed on demand from the plan tree. The plan tree in the database is the single source of truth; no derived artifact may ever be read back as input for verification.

{z8c3} All plan data lives in a relational database (PostgreSQL with the pgvector extension) that ships inside the server deployment. The database is the single source of truth: entities are rows, history is an append-only revision log, cascade publication is a database transaction, and concept embeddings are stored next to the concepts they describe. The file layout of `plan_standard_machine.yaml` is retained as the import/export exchange format only, never as the operational store.

## 2. Stored entities

{v4n6} Plan is the root aggregate: identity, name, status, head revision, and references to its levels. The server hosts multiple plans in one database and lists them by catalog query. A plan also carries a user-set context budget in tokens — the ceiling that prompt assembly measures against; it is supplied by the user, set at plan creation, changeable later, varies from plan to plan, and defaults to 4000 tokens.

{b7d1} Paragraph is the addressable unit of the HRS (`source_spec.md`). A binding paragraph carries a stable four-character base36 label in curly braces at its start. Labels are position-independent, unique within one HRS, and survive reordering and external edits. The server treats HRS text as human-owned: it never authors or rewrites paragraph content, but it manages labels — it can list paragraphs, resolve a label to text, assign fresh labels to new unlabeled paragraphs, and toggle non-binding block markup.

{h3j9} Non-binding blocks are delimited by `<!-- non-binding -->` / `<!-- /non-binding -->` markers. Paragraphs inside them carry no labels, are excluded from concept extraction, and never participate in coverage checks.

{f6s2} Concept is an MRS entry: `concept_id` (C-NNN), canonical `name`, one-sentence `definition`, `properties`, and `source_labels` binding it to HRS paragraphs. Concepts form the semantic basis of the plan; they are selected to be as orthogonal as possible, and basis quality is itself measured (see scoring).

{g8l4} Relation is a typed edge between two concepts. Exactly seven types are allowed: uses, owns, implements, extends, depends_on, produces, consumes. Free-form relation types are rejected at write time.

{w2y7} Step is the single stored entity for levels 3–5. A Step has a level (global, tactical, atomic), a zero-padded `step_id` (G-NNN / T-NNN / A-NNN) unique within its scope, a kebab-case slug matching its directory or file name, level-specific required fields, `depends_on` references, `concepts` references into the MRS, and a status. The operations on a Step (create, read, update, move, delete, set status, list, tree) are uniform across levels; the differing required-field sets are declarative schema, not separate APIs.

{u5e9} The identifier patterns, per-level required fields, and the exchange-layout naming are described by a declarative PlanSchema configuration object with defaults matching `plan_standard_machine.yaml`. Nothing project-specific is hard-coded in the engine; a conforming plan works out of the box, and exotic layouts are supported by overriding PlanSchema values.

{n1o3} Statuses follow the standard: draft, ready_for_review, frozen, needs_review for all artifacts, plus in_progress and done for atomic steps only. The server enforces legal transitions and performs automatic needs_review propagation during cascade.

{q2r9} Persistence model: every entity mutation writes a new immutable node version into an append-only store and produces its own revision record — one mutation, one revision — so the plan state after any individual edit is addressable. In direct (draft) editing the head advances with each revision; cascade revisions chain under the cascade ref and reach the head only on publication. Any past plan state is reconstructable by revision id, and the difference between two revisions is computable by query. Referential integrity of identifiers (parent links, depends_on targets, concept references, relation endpoints) is enforced by the database schema at write time, in addition to the gate's set-level checks.

{t6s8} Every stored entity — plan, paragraph, concept, relation, step, node version, revision, cascade — carries an immutable UUID assigned at creation as its primary identity in the database. Human-readable identifiers (C-NNN, G-NNN, T-NNN, A-NNN, paragraph labels) are stable addressable names unique within their scope and mapped to UUIDs; renames and moves change names, never UUIDs. Derived, computed keys (such as the module classification key of the object axis) are not identities and receive no UUIDs.

{d5i9} The version store is git-like and consists of three table families: node versions (blob analog — immutable, content-addressed by the hash of the node's canonical serialization; identical content stored once), revisions (commit analog — id, parent revision id, author, message, timestamp, and the set of node versions that changed relative to the parent), and refs (branch analog — the plan head ref plus one ref per open cascade, each pointing at a revision). The canonical serialization is canonical JSON — lexicographically sorted keys, UTF-8, no insignificant whitespace — hashed with SHA-256. Publication moves the head ref; a cascade is a ref whose revision chain is merged into head on commit and deleted on abort.

{e2b8} Version operations available over this store: log (revision chain of a plan or one node), diff (two revisions → added/removed/changed nodes with field-level detail), checkout-read (any command that reads plan state accepts an optional revision and reads that snapshot), and revert (a new revision that restores a prior state — history is never rewritten, only appended). Exports at a named revision use checkout-read.

{z6n1} A per-plan advisory lock in the database serializes cascades and identifier assignment. All concurrency control lives in the database; the server keeps no lock files and no in-process lock state that would be lost on restart.

{v1c8} Exchange format: dedicated commands export and import plans as files in the standard `plan_standard_machine.yaml` directory layout. File formats are fixed: the HRS is Markdown (`source_spec.md`); every other artifact is YAML (`spec.yaml` for the MRS, `README.yaml` for global and tactical steps, `A-NNN-<slug>.yaml` for atomic steps). `plan_export` materializes a plan — optionally at a named revision — into that tree; `plan_import` ingests such a tree. `hrs_import` parses a human-authored `source_spec.md`, assigns missing labels, and stores the paragraphs; `hrs_export` regenerates the Markdown byte-stable. Exported files are derived snapshots and are never read back as truth except through explicit import.

{b8j5} Concept embeddings are cached in the database as a vector column keyed by the content hash of the embedded serialization; changing a concept invalidates its cached vector automatically. No vector data exists outside the database.

## 3. Derived views (computed, never stored)

{c9a6} Branch is the unit of verification and prompt assembly: one path HRS-slice -> GS -> TS -> AS, where the HRS slice is the set of binding paragraphs claimed by the branch via source_labels. Branches are addressable (for example `G-002/T-003`) but never materialized as files.

{d4r8} DependencyGraph is a set of projections computed from the tree: execution order (from `depends_on` at every level plus priority within a target file at the atomic level), a parallelism map of units that may proceed concurrently, cycle detection, and impact analysis answering "which nodes become needs_review if this node changes".

{e7i2} Coverage views replace the former matrix files: concept coverage of the MRS by global steps, per-GS concept coverage by tactical steps, the object/work-axis inventory derived from atomic step object declarations, and label coverage of the HRS by global steps. Each view is recomputed from the tree at query time.

{t3u5} Prompt is the assembled executor input for one atomic step: the AS delta plus its inherited path up (TS, GS, the HRS slice by source_labels, and the MRS excerpt for the concepts the AS declares). Assembly is a pure deterministic function of the tree; the engine resolves declared concepts but never chooses them.

{y6q1} Prompts are ephemeral. An optional dump operation may materialize all prompts as a derived snapshot for human reading or handoff, but a snapshot is never read back as input to any check.

## 4. Verification: mechanical gate

{x8m3} The mechanical gate is deterministic and exhaustive over mechanics: YAML parseability; directory-name/step_id agreement; identifier pattern and zero-padding conformance; step_id uniqueness within scope; priority uniqueness within (target_file, TS); single non-empty project-relative target_file per AS; structured inputs/outputs; resolution of every reference — depends_on targets, concept_id into the MRS, relation endpoints and types, source_labels into binding HRS paragraphs; and the set-theoretic coverage checks computed on the fly (MRS concepts covered by GS set, per-GS concepts covered by TS set, object-axis single-realization and no-collision, HRS binding labels covered by GS set).

{s2z9} The gate is a precondition for semantic measurement. A branch with any mechanical finding is not measured; the gate reports the exact offending items with artifact paths and stops there. Occurrences are always classified by artifact path, never by bare step number, because step numbers repeat across parents.

{j5k7} Gate output is machine-checkable: a per-check PASS/FAIL report with offending items, plus a JSON mode with an overall green flag. Exit semantics: green only when every check passes. Parser sanity gates (for example expected non-zero entity counts) make parsing regressions fail loudly instead of passing silently.

## 5. Layer interaction: mechanics first, semantics on clean mechanics only

{h7u3} The two layers form a strictly ordered pipeline: mechanics catches mechanical defects; semantics runs only on mechanically clean material. This is a correctness rule, not an optimization — every semantic estimator presupposes that references resolve, structures parse, and coverage sets are computable. An index computed over broken mechanics is noise that misleads, which is strictly worse than no index.

{f1w9} Gating is per-branch: a mechanically clean branch is measurable even while sibling branches still carry mechanical findings, so authoring can interleave fixing and measuring on a narrow front. The plan-level semantic index, however, is published only when the entire plan is gate-green; until then the plan verdict is the gate report itself.

{g3o6} A gate verdict is bound to the exact tree state it was computed on, identified by the plan revision id. Any mutation invalidates the verdict for the affected scope; `plan_score` checks gate freshness for its scope against the current revision and re-runs the gate (or refuses) rather than measure a scope whose gate verdict is stale.

## 6. Verification: semantic scoring

{l9b4} The semantic index of a branch is the cosine between the concept vector the branch must express (its HRS slice mapped through source_labels onto the MRS basis) and the concept vector it actually expresses across GS, TS, and AS — computed in the concept basis, not between raw texts. The index is reported normalized (0..100).

{o3v8} Basis quality is measured before branch scoring: pairwise concept cosines, Gram determinant, and spectrum of the concept embedding set yield a trust value for the measurement itself. A non-orthogonal basis or an unavailable embedding service lowers trust, and the report distinguishes "the plan is weak" from "the plan cannot be measured".

{i7h2} The scoring instrument is an ensemble of weak independent estimators: deterministic concept-coverage of the slice, deterministic reference resolution, the embedding cosine, and an executor simulation in which a cheap generative model is asked the closed question "name every entity the prompt uses but does not define"; its output is treated as suspicion and filtered deterministically against the prompt text. The model is a detector, never a judge. Estimators sharing the same physics are down-weighted so one signal is not double-counted.

{p4g6} Output discipline: in the normal case a human sees one number and a color per plan, with the few weakest branches ranked. The internal estimator vector and the trust value surface only for a branch that misses the threshold. Plan-level aggregation is conservative (minimum branch index or fraction-above-threshold; the exact form is a development-phase parameter).

## 7. Cascade and lifecycle

{a8w1} All plan mutations flow strictly top-down per the standard cascade. Direct edits of the MRS are forbidden outside a cascade; the server rejects them.

{k6f3} CascadeChange is a transaction. It opens as a git branch of the plan repository; mutations are applied there; a preview computes the blast radius (which descendants transition to needs_review per the invalidation rule) and runs the mechanical gate; commit publishes by merging into the plan main branch only when the gate is green; abort discards the branch. Intermediate states are never visible to plan consumers.

{m2d9} needs_review propagation is automatic within a cascade: when any node changes, all its direct children are marked needs_review, recursively as reviewed children change. HRS changes trigger MRS re-projection; MRS changes invalidate all global steps; a changed GS invalidates its TS set; a changed TS invalidates its AS set.

{q9n5} Finding is the ephemeral result unit of gate and scoring runs: check id, severity, artifact path, message. Reports aggregate findings plus an overall verdict; they are returned to the caller and optionally logged, never stored as plan artifacts.

## 8. Command surface

{r1c7} Commands are grouped by entity with stable prefixes: `plan_*` (including `plan_export`/`plan_import`), `para_*`, `hrs_export`/`hrs_import`, `concept_*` and `relation_*`, `step_*`, `graph_*`, `branch_*`, `plan_validate`, `plan_score`, `cascade_*`, and the server self-description command `info`. The groups below define the working behavior of each tool at the level of inputs, effects, and outputs; exact parameter schemas belong to lower plan levels. The editing (mutating) subset is exactly: `plan_create`, `plan_import`, `hrs_import`, `para_label_assign`, `para_mark_non_binding`, `concept_add`, `concept_update`, `concept_remove`, `relation_add`, `relation_remove`, `step_create`, `step_update`, `step_move`, `step_delete`, `step_set_status`, `cascade_begin`, `cascade_commit`, `cascade_abort`; every other command is read-only.

{z5t4} Read commands never mutate disk. Write commands are explicit, validate before acting, and verify their own result by re-reading after write. Destructive or bulk operations expose a dry-run mode that defaults to on.

{i5n7} Mutation regime depends on artifact status: while an artifact is draft or ready_for_review, direct mutation commands operate on the plan main branch; once an artifact is frozen, any change to it or above it is rejected outside an open cascade and must go through `cascade_*`. MRS entities (concepts, relations) are the exception: they are cascade-only at any status, because the standard forbids direct machine_spec edits.

{p8q4} `plan_create` initializes a new plan: creates the plan aggregate in the database at revision zero with an empty HRS and an empty MRS, and returns the plan identity. `plan_list` queries the catalog and returns each plan with its status summary. `plan_status` returns the dashboard for one plan: artifact counts per level, status distribution, gate verdict, semantic index with trust, and the ranked list of weakest branches. `plan_export` / `plan_import` and `hrs_export` / `hrs_import` move plans between the database and the file exchange format per {v1c8}.

{a1z3} `para_list` parses the HRS and returns every paragraph with its label, binding flag, and position; `para_get` resolves one label to its text. `para_label_assign` finds binding paragraphs that lack labels and inserts fresh unique labels at paragraph start — the only textual edit the server is allowed to make in the HRS. `para_mark_non_binding` wraps or unwraps a paragraph range in non-binding markers. All `para_*` mutations are line-precise and leave surrounding prose byte-identical.

{k7r9} `concept_get` / `concept_list` / `relation_list` read the MRS. `concept_add`, `concept_update`, `concept_remove`, `relation_add`, `relation_remove` require an open cascade and enforce required fields, C-NNN identifier discipline, the seven relation types, endpoint existence, and source_labels resolution at write time — a mechanically invalid MRS entry cannot be written at all. `concept_coverage` answers reverse queries: which steps at which levels reference a given concept, and which HRS paragraphs justify it.

{m4c2} `step_get` returns one step with resolved context (parent chain, children list, referenced concepts). `step_tree` returns the plan tree or a subtree with statuses. `step_update` patches fields of one step under the level schema and re-validates references it touches. `step_move` renames or reparents a step, renumbering directories and rewriting every `depends_on` and list reference to the moved id in one operation. `step_set_status` enforces the legal transition graph and refuses transitions the cascade rules reserve for the server itself (needs_review is set only by cascade propagation).

{q6d8} `graph_deps` returns the dependency neighborhood of one node in both directions. `graph_order` returns a topological execution order for the plan or a subtree, combining `depends_on` at every level with priority ordering within each (target_file, TS) pair, and fails with the cycle listed when ordering is impossible. `graph_parallel_map` partitions steps into waves of units with no path between them — what may proceed concurrently. `graph_impact` answers "if this node changes, which descendants become needs_review and which branches must be re-verified", without changing anything.

{r9f1} `branch_prompt` assembles the executor prompt for one atomic step deterministically from the tree (AS delta, parent TS and GS, HRS slice by source_labels, MRS excerpt for declared concepts) and returns it with its token estimate against the plan's user-set context budget. `branch_dump` materializes all prompts of a plan as a derived snapshot directory, explicitly marked non-authoritative. `branch_weak` returns branches ranked by ascending semantic index.

{z2b5} `plan_validate` runs the mechanical gate with a scope selector (full plan, one level, one branch, or one group of checks), a fail-fast flag, and report or json output. It is pure read: it never fixes anything. Every finding names the check id, the offending artifact path, and the exact items, so the fix location is unambiguous.

{v6t8} `plan_score` runs the semantic layer on a branch or the whole plan, refusing scopes that have not passed the gate in the same tree state. It returns the normalized index, the trust value, and the color verdict; per-estimator internals are included only for branches below threshold or on explicit request. When the embedding service is down it returns the deterministic estimators plus an explicit low-trust marker instead of failing.

{b4x2} `cascade_begin` opens a transaction: acquires the per-plan lock, anchors a change set at the current head revision, and returns the cascade id that all mutation commands inside the transaction must carry. `cascade_preview` reports the accumulated change set, the needs_review blast radius, and the gate verdict for the cascade state. `cascade_commit` atomically advances the plan head to include the change set and is refused while the gate is red; `cascade_abort` discards the change set and leaves the plan untouched. One plan admits one open cascade at a time.

{v8y2} `step_create` is the scaffolder: it creates the level-specific required-field skeleton with status draft, auto-assigns the next free zero-padded id within the parent scope, and rejects duplicates. Content is stored structurally in the database, so YAML quoting hazards exist only at export time and are handled by the safe emission rule.

{b3e6} Every command resolves plan identity against the database catalog. Database connection parameters and storage locations come from server configuration only and are never accepted as request parameters.

## 9. Normative algorithms

{w5e2} The algorithms in this section are normative. Lower plan levels refine them into code without altering their semantics. Any deviation or gap discovered during implementation escalates back to this document; it is never resolved by executor improvisation. Where a parameter is genuinely open, this document names its default and declares the alternatives configuration — an executor picks neither.

{u8s4} HRS parsing: the HRS text splits into paragraphs on blank-line boundaries. A paragraph whose first non-whitespace characters match `{`, exactly four base36 characters, `}`, one space is labeled. Non-binding regions are the non-nesting maximal ranges between `<!-- non-binding -->` and `<!-- /non-binding -->`; a paragraph inside such a range is non-binding regardless of labels. Heading lines and fenced code blocks are never binding paragraphs.

{n2j7} Label assignment: collect the set of labels already present; for each unlabeled binding paragraph in document order, draw four characters uniformly from `[0-9a-z]`, retry on collision with existing or just-assigned labels, and insert `{xxxx} ` at the paragraph start. Existing labels are never rewritten, reused, or reordered.

{c6f9} Gate execution: checks run in a fixed published order — parse, identity (dir/step_id, patterns), uniqueness, reference resolution, coverage. Each check sees the whole tree and emits findings sorted by (artifact path, check id). With fail_fast the run stops only at a check-group boundary, so partial output is still deterministic. Two runs over the same tree state produce byte-identical reports.

{d1t3} Coverage formulas: plan concept coverage compares union(concepts of all G-steps) against MRS concept ids for set equality; per-GS coverage requires union(concepts of its T-steps) to be a superset of the GS concepts; label coverage compares union(source_labels of all G-steps) against the binding labels of the HRS; relation coverage compares union(relations implemented by G-steps) against MRS relations. Every comparison reports missing and extra elements explicitly, never a bare boolean.

{e8p5} Object-axis inventory: objects are collected from the object declarations of AS files. The owner key of an object is the pair (module derived from target_file, tactical step path). The module is derived deterministically: strip the file extension and replace path separators with dots (a target file `a/b/c.py` yields module `a.b.c`). Findings: an object name with more than one owner key, an object name spanning more than one module, an object concept set not a subset of the union of its AS concept sets. Classification is always by full artifact path, never by bare step number.

{t2a7} Ordering and cycles: graph nodes are steps; edges are every `depends_on` at every level plus an edge between each consecutive priority pair within one (target_file, TS). Topological order is Kahn's algorithm with the deterministic tie-break: among ready nodes, ascending (level, parent path, step_id). If the ready queue empties early, the residual subgraph is reported as the cycle set.

{y9k4} Parallel waves: wave 0 is the set of nodes with no prerequisites; wave N+1 is the set whose prerequisites all lie in waves 0..N. Waves are listed in order, nodes within a wave sorted by the same tie-break as ordering.

{x4v1} Impact: computed by the invalidation rule as breadth-first descent — direct children of the changed node first, then recursively through nodes whose status would actually change. Impact of an HRS paragraph starts by resolving the concepts citing its label in source_labels and the G-steps claiming it, then descends normally.

{s5m8} Prompt assembly is concatenation by reference in a fixed order: (1) MRS excerpt — definitions and relations of exactly the concepts the AS declares, ascending by concept id; (2) HRS slice — binding paragraphs whose labels appear in the parent GS source_labels, in document order; (3) parent GS content; (4) parent TS content; (5) the AS delta. The engine resolves declared references only; it never adds, drops, or reorders content by judgement. The same tree state yields a byte-identical prompt.

{j8b2} Semantic vectors: a concept axis embedding is the embedding of a fixed serialization of the concept (default: the definition field only; richer serializations are configuration). c_required of a branch is the concept set reachable from its HRS slice via source_labels; c_actual is the concept set declared across the branch GS, TS, and AS. The branch index is the cosine between the two vectors expressed in the concept basis, mapped to 0..100; per-concept weights are configuration with published defaults.

{l2q6} Trust: compute pairwise cosines of the normalized concept embeddings, the Gram matrix, its determinant and eigenvalue spectrum. Trust decreases monotonically with basis collinearity and drops to a declared floor when the embedding service is unavailable. The monotone mapping is configuration with a published default.

{o7d4} Executor simulation: the detector model receives each assembled prompt with the single closed question "name every entity this prompt uses but does not define" and returns a list of names. The engine deterministically discards every returned name that does occur in the prompt text; the surviving fraction is the estimator value. The detector can only raise suspicion; it can never mark a branch green.

{i3g8} Ensemble aggregation: estimator votes combine through a transparent weighted fold with published default weights; estimators of the same physics (the two embedding-based ones) share one down-weighted vote. Plan-level aggregation defaults to the minimum branch index; fraction-above-threshold is the configurable alternative.

{p6h1} Cascade mechanics: `cascade_begin` acquires the per-plan advisory lock and opens a change set anchored at the plan head revision; every mutation inside the transaction writes new node revisions attributed to the cascade without moving the head; `cascade_preview` is the change set against the head plus impact computation plus a gate run over the cascade state; `cascade_commit` atomically advances the head to the cascade state only when that gate run is green and releases the lock; `cascade_abort` discards the cascade's revisions and releases the lock.

{a9y5} Next-free id: within the parent scope, collect the numeric ids matching the level pattern, assign max+1 (1 for an empty scope), zero-padded to three digits. Assignment re-checks under the per-plan lock so concurrent creates cannot obtain the same id.

{k4u7} Safe YAML emission (export path): any scalar containing `: `, a leading `-`, quotes, `#`, or other YAML metacharacters is emitted as a quoted or block scalar. Every emitted file must round-trip through the standard YAML parser to an identical value tree before the export completes; a failed round-trip aborts the export. `hrs_export` must reproduce stored paragraph text byte-identically.

{m7w3} Verdict freshness: every gate and score result records the plan revision id (head, or cascade state id) and the scope it was computed for. A verdict is fresh iff the recorded revision equals the current revision of the measured state. Freshness is decided by revision comparison, never by timestamps.

## 10. API command standard: schemas, metadata, self-description

{t4k1} Every command class follows the adapter contract verified against mcp_proxy_adapter sources: ClassVar attributes `name`, `version`, `descr`, `category`, `author`, `email`; a `result_class` referencing a SuccessResult subclass that defines its own result schema; `use_queue = True` only on the commands this document declares long-running. `descr` is the one-line summary that the adapter surfaces in `help` and OpenAPI; it must be non-empty for every command.

{y2m6} `get_schema()` returns the strict subset the adapter validator actually enforces: `type: object`; every public parameter present under `properties` with `type` and `description`; `required` listing exactly the runtime-required parameters; `additionalProperties` always explicit and `false` for every plan_manager command; `enum` for fixed modes (level, scope, output format); `default` only where `execute()` actually applies that default; numeric bounds via `minimum`/`maximum`; array item types via `items`. Complex commands keep the schema in a sibling `<command>_schema.py` module exposing `get_<command>_schema()`.

{h2f8} The adapter schema validator is shallow: it checks types, required, enum, bounds, and unknown keys, but not nested object structure. Therefore every command with nested parameters implements the missing depth in `validate_params()`: first `super().validate_params(params)` (schema layer), then semantic checks — plan existence, cascade id validity, revision existence, mutually exclusive parameters, ordering constraints — raising ValidationError with field and details. Semantic validation runs before any queued work is accepted.

{f4d6} `metadata()` returns the full documentation dictionary per the metadata standard: identity keys mirrored from class attributes; `detailed_description`; `parameters` as {description, type, required, default, examples} per parameter; `return_value` with success {description, data field map, example} and error {description, code, message}; `usage_examples` as plain parameter dictionaries (never transport envelopes) each with description and explanation; `error_cases` keyed by stable string code with description, message template, and solution; `best_practices`. `metadata()` must never contradict `get_schema()`. Complex commands keep it in `<command>_metadata.py` taking the command class as argument.

{g9b1} Error model: adapter exceptions map to JSON-RPC codes (ValidationError/InvalidParams -32602, MethodNotFound -32601, Internal -32603, domain CommandError -32000); command-level failures return ErrorResult carrying a stable domain string code — PLAN_NOT_FOUND, STEP_NOT_FOUND, REVISION_NOT_FOUND, CASCADE_REQUIRED, CASCADE_CONFLICT, FROZEN_ARTIFACT, GATE_RED, VERDICT_STALE, EMBEDDINGS_UNAVAILABLE, IMPORT_INVALID, and their peers. Every code listed in a command's error_cases must be actually returnable by that command, and every returnable code must be listed.

{w6t5} The command inventory is closed and normative: the plan_manager API consists of exactly the commands named in this document — the groups of the command surface section plus `info`. A command not named here must not exist in the registry; adding or removing a command is a cascade change to this HRS first, then to the code.

{u3x7} The `info` command returns the server self-description: identity (product name, package version, adapter version), build metadata (build date, image tag), runtime summary (database connectivity, embedding service reachability, open cascade count), and the full operator documentation text. The documentation payload is rendered at build time from the single documentation source and embedded into the package as data consumed by the `info` command — the same source that produces the installed man and info pages, so the API documentation and the installed documentation cannot diverge.

{n5c2} Startup self-check — registration completeness: after hook registration the server compares the registry contents against the normative inventory. A missing command, an unexpected extra command, or a duplicate name aborts startup with a report naming the exact difference. The server never starts with a partial API surface; "implemented but not registered" is a startup failure, not a silent gap.

{d7e4} No-stub guarantee: at startup every registered command is probed — `get_schema()` must return a schema with explicit `additionalProperties` and the declared parameters; `metadata()` must contain every required key with non-empty content; `descr` must be non-empty. Any probe failure aborts startup. A command is either implemented completely or not registered at all; placeholder implementations (empty execute bodies, NotImplementedError paths) must never be reachable through a registered command.

## 11. Platform: mcp-proxy-adapter

{h9s1} The server is built on mcp_proxy_adapter (>= 8.10.15). Every command is a class subclassing `mcp_proxy_adapter.commands.base.Command` with class attributes name, version, descr, category, author, email, returning `SuccessResult` or `ErrorResult`; each command implements `get_schema()` (machine-readable input schema), `metadata()` (extended documentation with usage examples, error cases, best practices), and semantic validation beyond the schema, per the metadata standard.

{f2x7} Commands are registered through the adapter hook mechanism: a hooks module calls `register_custom_commands_hook(...)`, and the callback registers every command class via `registry.register(CommandClass, "custom")`. Modules needed by spawned worker processes are declared with `register_auto_import_module`.

{g5j8} The adapter owns the external surface: JSON-RPC endpoint `/api/jsonrpc` (single and batch), `/api/async`, `/health`, `/commands`, `/heartbeat`, WebSocket job push, OpenAPI and help output. plan_manager registers command classes only; it must not patch adapter internals and must not add custom HTTP routes.

{w7l3} Long-running operations (full-plan scoring, large cascade previews) set `use_queue = True` on the command class so the adapter executes them through its queue manager with job_id/polling semantics; quick navigation and single-node reads stay synchronous.

{u1p9} The entry point is `python -m plan_manager.main --config <config.json>`: validate configuration, create the FastAPI application through the adapter AppFactory (`create_app`), and run it with the adapter hypercorn engine. Supported protocols are http, https, and mtls exactly as provided by the adapter configuration.

## 12. Configuration

{n6a4} Configuration is a single JSON file. Adapter-owned sections (server, registration, auth, queue_manager, and optional ssl/transport/security) follow adapter semantics unchanged. plan_manager adds one custom top-level section `plan_manager`, which the adapter tolerates by design (unknown sections produce warnings only).

{c3k8} The `plan_manager` section is validated at startup by an own Pydantic model with an allowed-keys check, following the reference consumer pattern: parsing the JSON stays adapter-native dict access, while the Pydantic model is the single definition of allowed fields, types, and defaults. Invalid configuration aborts startup with an explicit report.

{d8o2} The `plan_manager` section fields: `database` (required; connection parameters for the in-container PostgreSQL — socket or host, port, dbname, user; the password comes from a mounted secrets file, never from config), `embedding` (optional: `url`, `model`, timeout), `scoring` (optional, with published defaults: `threshold` 85, `aggregation` minimum, `concept_weights` uniform 1.0, `embedding_serialization` definition-only, `estimator_weights` — deterministic coverage 1.0, the embedding-based pair sharing a single vote of 1.0, executor simulation 1.0 — and `trust_floor` 0.2), `schema_overrides` (optional PlanSchema deviations for the exchange layout), `export_root` (default directory for file export/import when the caller passes a relative path). The per-plan context budget is plan data supplied by the user, not a configuration field. No field of this section is ever taken from request parameters.

{e5m7} Proxy participation is configured through the adapter `registration` section (register_url, heartbeat URL and interval, server_id, instance UUID). Registration and heartbeat run automatically on startup when enabled; the server functions identically with registration disabled.

## 13. Deployment (container)

{t9v1} The server ships as a single container image hosting both the plan_manager process and its PostgreSQL instance (with pgvector). The entrypoint starts PostgreSQL, waits for readiness, then launches the server with the config file mounted read-only at a fixed path and passed via `--config`. The image uses a slim Python base and a non-root runtime user.

{y4b6} Host filesystem contract is fixed: `/etc/planmgr` holds configuration and secrets (mounted read-only into the container), `/var/planmgr` holds data including the PostgreSQL data directory (mounted read-write), `/var/log/planmgr` holds logs (mounted read-write). Everything mutable lives on the host through these mounts; no plan data, configuration, or secrets are baked into the image, so plan data survives container replacement and upgrade.

{h5o2} A dedicated system user and group own the deployment on the host: `planmgruser:planmgrgrp`. The three mounted directories are owned by them with restrictive modes, and the container processes run under the matching uid/gid so every file created through the mounts is owned by `planmgruser:planmgrgrp` on the host.

{f9l7} A single release script builds the container image, tags it with the package version, pushes it to Docker Hub, and builds the Ubuntu installation package (deb) targeting the current Ubuntu release. The version is single-sourced from the package definition; image tag and package version always agree.

{g7s4} The installation package, on install: creates `planmgruser`/`planmgrgrp` if absent, creates the three directories with correct ownership and modes, and installs configuration templates as conffiles — when a file already exists and was modified, the standard overwrite prompt applies; nothing is silently replaced.

{e9a3} The package installs operator documentation as man page(s) and a GNU info document. Their content and the documentation payload embedded into the API `info` command are rendered at build time from one documentation source by the release script; a build where the three renderings would diverge must fail.

{w3x9} Deployment flow after install: operator settings are read from `/etc/default/planmgr` (image version, published port, advertised host, registration toggles, database parameters); the installer verifies that the required image version exists on Docker Hub and pulls it; the server config under `/etc/planmgr` is rendered from those settings; the container is created and started with the three mounts attached.

{u6z2} A systemd service owns the container lifecycle (create, start, stop, restart on failure) and runs as `planmgruser`. It reads `/etc/default/planmgr` as its environment file, depends on the container runtime, and reports readiness through the adapter `/health` endpoint.

{n8e5} The package ships database initialization commands, invocable standalone and through the service wrapper: first-run initialization of the mounted PostgreSQL data directory (initdb when empty), creation of the role and database, applying schema migrations, and setting the password from the secrets file. Initialization is idempotent — safe to re-run and refusing to damage an existing database.

{x2h9} The container exposes one service port and defines a healthcheck against the adapter `/health` endpoint. When registration is enabled, the advertised host/port in configuration must be reachable by the proxy from outside the container network namespace.

## 14. Non-goals

{s7g3} The server does not author or modify HRS prose; HRS content is human-owned. Verification findings whose resolution requires HRS changes halt and report to the human.

{j1w5} The server does not execute atomic-step prompts, orchestrate coder models, or track code implementation; its scope ends at plan artifacts and their verification.

{l4u8} The server performs no vectorization pipeline of its own and produces no vector files; embeddings are requested on demand from the configured service and cached only in the database keyed by content hash.

{o9f2} The server does not merge unrelated concerns from other servers: no file editing surface for non-plan files, no code analysis, no proxying of third-party commands.
