# Plan Manager per-table schema inventory

Produced by G-001/T-001/A-001 of plan `planmgr-cr6-entity-identity-crud`.

Sources of every statement below: the numbered migration chain
`plan_manager_db/migrations/0001_initial_schema.sql` through
`0025_wish_and_calendar_entries.sql`, the identity registry module
`plan_manager/storage/identity.py`, the store-level hard-deletion module
`plan_manager/storage/runtime_hard_delete.py`, the entity base
`plan_manager/domain/entity.py`, and the normative command registry
`plan_manager/commands/inventory.py`.

This document records facts only. It proposes no design.

## Method and vocabulary

Every table created anywhere in the migration chain gets one row-group. Each
row-group carries exactly these eight facets:

1. **Identifier column and type.**
2. **Semantic owner/reference columns** — `plan_uuid`, `step_uuid`,
   `revision_uuid`, the `anchor_*` family, project columns, link columns.
3. **FK-backed references** with their `ON DELETE` behaviour.
4. **Plain (non-FK) reference columns** — columns that hold another entity's
   identifier without a database-level foreign key.
5. **Soft-delete column** — `deleted_at`, or none.
6. **Hard-delete path** — which code performs irreversible removal today: a
   reference-check table entry, a store-level delete, or none.
7. **Get/list/search command coverage** — which MCP commands read this table.
8. **Identity-registry participation** — presence or absence in
   `identity.py` `ALLOWED_TABLES` and in the registry triggers.

Two registry mechanisms exist and they do not agree. The database side is a
pair of triggers per table (`entity_identity_<table>_insert` calling
`register_entity_identity_trigger('<table>', '<entity_type>')`, and
`entity_identity_<table>_delete` calling `unregister_entity_identity_trigger()`),
introduced in `0015_entity_identity_registry.sql` and extended by
`0016_runtime_link.sql`, `0018_agent_config_entities.sql` and
`0025_wish_and_calendar_entries.sql`. The Python side is the
`ALLOWED_TABLES` frozenset in `plan_manager/storage/identity.py`, which admits
exactly eight tables: `plan`, `paragraph`, `concept`, `relation`, `step`,
`node_version`, `revision`, `ref`. Facet 8 reports both independently.

Table count: **43**.

---

## Plan-truth tables

### plan

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `head_revision_uuid`; `project_ids text[]` and
   `primary_project_id text` (added in `0003_project_bindings.sql`) carry
   external project identifiers.
3. **FK-backed:** `head_revision_uuid -> revision(uuid)`, `NO ACTION`, added as
   a deferred constraint in `0001_initial_schema.sql`.
4. **Plain references:** `project_ids`, `primary_project_id` — external project
   UUIDs held as text, deliberately not FK-backed because no local project
   table exists.
5. **Soft delete:** `deleted_at timestamptz NULL` (`0006_plan_soft_delete.sql`).
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["plan"]` in
   `plan_manager/domain/entity.py`, plus `Plan.HARD_DELETE_REFERENCE_CHECKS` in
   `plan_manager/domain/plan.py`; executed through `hard_delete_entity`. No
   entry in `runtime_hard_delete.py`.
7. **Commands:** `plan_list`, `plan_project_list`, `plan_status`, `plan_export`,
   `plan_snapshot`, `plan_score`, `plan_validate`. There is no `plan_get`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `plan`.

### paragraph

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** none.
5. **Soft delete:** none.
6. **Hard-delete path:** `hard_delete_entity` via the entity base; no
   per-entity reference-check table, no `runtime_hard_delete.py` entry.
7. **Commands:** `para_get`, `para_list`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `paragraph`.

### concept

1. **Identifier:** `uuid uuid PRIMARY KEY`; business key `UNIQUE (plan_uuid, concept_id)`.
2. **Owner/reference columns:** `plan_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** `source_labels text[]` holds HRS paragraph labels, not
   identifiers.
5. **Soft delete:** none. `Concept.SOFT_DELETE_COLUMN` is `None`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["concept"]` plus
   `Concept.HARD_DELETE_REFERENCE_CHECKS` in `plan_manager/domain/concept.py`;
   referrers are matched on the scoped `(plan_uuid, concept_id)` key, not on
   `uuid`.
7. **Commands:** `concept_get`, `concept_list`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `concept`.

### relation

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** `from_concept text`, `to_concept text` — scoped
   references to `concept.concept_id` within the same `plan_uuid`, with no FK.
5. **Soft delete:** none. `Relation.SOFT_DELETE_COLUMN` is `None`.
6. **Hard-delete path:** `hard_delete_entity`; relations are the referring
   side, never the referenced side.
7. **Commands:** `relation_list`. There is no `relation_get`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `relation`.

### step

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `parent_step_uuid`, `project_id`
   (added in `0003_project_bindings.sql`).
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** `parent_step_uuid` — self-reference with no FK;
   `concepts text[]` — scoped references to `concept.concept_id`;
   `depends_on text[]` — sibling step ids; `project_id` — external project.
5. **Soft delete:** none. `Step.SOFT_DELETE_COLUMN` is `None`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["step"]` plus
   `Step.HARD_DELETE_REFERENCE_CHECKS` in `plan_manager/domain/step.py`.
7. **Commands:** `step_get`, `step_list`, `step_tree`, `step_search`,
   `step_dependency_list`, `step_dependency_preview`, `graph_deps`,
   `graph_dependents`, `graph_order`, `graph_parallel_map`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `step`.

### step_runtime

1. **Identifier:** `step_uuid uuid PRIMARY KEY` — the table is keyed by its
   parent step, not by an independent identifier.
2. **Owner/reference columns:** `step_uuid`, `plan_uuid`.
3. **FK-backed:** `step_uuid -> step(uuid) ON DELETE CASCADE`;
   `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** none.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own; removal happens only through the two
   `ON DELETE CASCADE` parents.
7. **Commands:** `step_runtime_get`, `step_runtime_list`, `step_runtime_report`.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### node_version

1. **Identifier:** `uuid uuid PRIMARY KEY`; content key
   `UNIQUE (plan_uuid, entity_uuid, hash)`.
2. **Owner/reference columns:** `plan_uuid`, `entity_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** `entity_uuid` — the versioned node's identifier
   (a step, paragraph, concept or relation uuid), polymorphic and deliberately
   not FK-backed.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own; removal only through the
   `ON DELETE CASCADE` parent. The version store is append-only.
7. **Commands:** none. No `version_*` command is registered in
   `plan_manager/commands/inventory.py`; the version primitives are consumed
   internally by `plan_manager/storage/version_ops.py`.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `node_version`.

### revision

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `parent_uuid`,
   `node_version_uuids uuid[]`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `parent_uuid -> revision(uuid) NO ACTION`.
4. **Plain references:** `node_version_uuids uuid[]` — an array of
   `node_version.uuid` values with no FK.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own; append-only, removed only through the
   `ON DELETE CASCADE` parent.
7. **Commands:** none directly; revisions surface through `plan_status`,
   `cascade_preview` and step reads.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `revision`.

### ref

1. **Identifier:** `uuid uuid PRIMARY KEY`; business key
   `UNIQUE (plan_uuid, name)`.
2. **Owner/reference columns:** `plan_uuid`, `revision_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `revision_uuid -> revision(uuid) NO ACTION`.
4. **Plain references:** none.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own.
7. **Commands:** none directly; refs are resolved internally by the version
   store.
8. **Registry:** in `ALLOWED_TABLES`; triggers present (`0015`), entity type
   `ref`.

### cascade

Created as a quoted identifier, `CREATE TABLE "cascade"`, because `cascade` is
a reserved word.

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `base_revision_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `base_revision_uuid -> revision(uuid) NO ACTION`.
4. **Plain references:** none.
5. **Soft delete:** none. A cascade leaves the live set by status
   (`open`/`committed`/`aborted`), enforced by
   `CREATE UNIQUE INDEX cascade_one_open ON "cascade" (plan_uuid) WHERE status = 'open'`.
6. **Hard-delete path:** none of its own.
7. **Commands:** `cascade_preview`; mutated by `cascade_begin`,
   `cascade_commit`, `cascade_abort`, `plan_unfreeze`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`, lines
   190 and 193, written against the quoted identifier `"cascade"`), entity type
   `cascade`.

### cascade_request

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `revision_uuid`,
   `target_step_path`, `origin_id`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `revision_uuid -> revision(uuid) NO ACTION`.
4. **Plain references:** `origin_id uuid` — polymorphic origin identifier
   discriminated by `origin_kind`, with no FK.
5. **Soft delete:** none. `CascadeRequestRecord.SOFT_DELETE_COLUMN` is `None`
   (append-only request log).
6. **Hard-delete path:** none of its own.
7. **Commands:** none registered.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `cascade_request`.

---

## Derived and cache stores

### context_block

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `revision_uuid`, `cascade_uuid`,
   `common_block_uuid`, `node_path`, `child_ref` (added in `0023`).
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `revision_uuid -> revision(uuid) NO ACTION`;
   `cascade_uuid -> cascade(uuid) NO ACTION`;
   `common_block_uuid -> context_block(uuid) NO ACTION`.
4. **Plain references:** `node_path`, `child_ref` — textual step addresses.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own; content-addressed by `content_hash`.
7. **Commands:** `block_get`, `block_list`, `block_rebuild`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `context_block`.

### srt_snapshot

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `revision_uuid`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`;
   `revision_uuid -> revision(uuid) NO ACTION`.
4. **Plain references:** none.
5. **Soft delete:** none. `SrtSnapshotRecord.SOFT_DELETE_COLUMN` is `None`
   (content-hash-deduplicated derived record).
6. **Hard-delete path:** none of its own.
7. **Commands:** `srt_snapshot_list`, `srt_diff`; created by
   `srt_snapshot_create`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `srt_snapshot`.

### runtime_audit_log

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `entity_id`,
   `linked_attempt_id`, `linked_review_id`.
3. **FK-backed:** `plan_uuid -> plan(uuid) ON DELETE CASCADE`.
4. **Plain references:** `entity_id uuid` — polymorphic, discriminated by
   `entity_type`; `linked_attempt_id -> execution_attempt.uuid` and
   `linked_review_id -> review_result.uuid`, both without FKs.
5. **Soft delete:** none. `RuntimeAuditRecord.SOFT_DELETE_COLUMN` is `None`;
   the trail is immutable and leaves only through the cascading plan parent.
6. **Hard-delete path:** none of its own.
7. **Commands:** `audit_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `runtime_audit`.

### command_metric

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** none.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** none. `CommandMetricRecord.SOFT_DELETE_COLUMN` and
   `UPDATED_AT_COLUMN` are both `None`, and `crud_update` is overridden to
   refuse (append-only timing log).
6. **Hard-delete path:** none of its own.
7. **Commands:** `command_timing_stats`.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### embedding_cache

1. **Identifier:** `uuid uuid PRIMARY KEY`; content key
   `content_hash text NOT NULL UNIQUE`.
2. **Owner/reference columns:** none.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** none.
6. **Hard-delete path:** none of its own; content-addressed cache.
7. **Commands:** none registered.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### entity_identity

The registry itself.

1. **Identifier:** `id uuid PRIMARY KEY` — note the column is `id`, not `uuid`.
2. **Owner/reference columns:** `table_name`, `entity_type` describe the owning
   row rather than pointing at it.
3. **FK-backed:** none.
4. **Plain references:** `id` is the identifier of a row in `table_name`, with
   no FK by construction — the registry spans every table.
5. **Soft delete:** none.
6. **Hard-delete path:** rows are removed by the
   `unregister_entity_identity_trigger()` AFTER DELETE triggers on the
   registered tables, and by `unregister_entity_identity` in
   `plan_manager/storage/identity.py`.
7. **Commands:** none registered.
8. **Registry:** it is the registry; not itself registered and not in
   `ALLOWED_TABLES`.

---

## Runtime work-layer entities

### todo_item

Entity type is `todo`; the table name is `todo_item`. The two differ.

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the full `anchor_*` family
   (`primary_anchor_type`, `anchor_project_id`, `anchor_file_path`,
   `anchor_plan_uuid`, `anchor_revision_uuid`, `anchor_step_uuid`,
   `anchor_step_path`, `anchor_ref_id`), plus `created_by` and `assigned_to`.
3. **FK-backed:** none.
4. **Plain references:** every `anchor_*` identifier column, including the
   polymorphic `anchor_ref_id` gated by `primary_anchor_type`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_todo` in
   `plan_manager/storage/runtime_hard_delete.py`, over
   `CENTRAL_REFERENCE_CHECKS["todo"]` and
   `TodoItem.HARD_DELETE_REFERENCE_CHECKS` in `plan_manager/domain/todo.py`.
7. **Commands:** `todo_get`, `todo_list`, `todo_queue`, `todo_resolve`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `todo`.

### todo_link

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `from_todo_uuid`, `to_todo_uuid`.
3. **FK-backed:** `from_todo_uuid -> todo_item(uuid) ON DELETE CASCADE`;
   `to_todo_uuid -> todo_item(uuid) ON DELETE CASCADE`.
4. **Plain references:** none.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** none of its own; both parents cascade.
7. **Commands:** `todo_link_add`, `todo_link_remove`. There is no
   `todo_link_list`; links surface through the todo read commands.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `todo_link`.

### runtime_comment

Entity type is `comment`; the table name is `runtime_comment`. The two differ.

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the full `anchor_*` family,
   `supersedes_comment_uuid`, `author`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** every `anchor_*` identifier column, the polymorphic
   `anchor_ref_id` gated by `primary_anchor_type`, and the self-reference
   `supersedes_comment_uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_comment` in `runtime_hard_delete.py`,
   over `CENTRAL_REFERENCE_CHECKS["comment"]`.
7. **Commands:** `comment_get`, `comment_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `comment`.

### execution_attempt

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `revision_uuid`, `step_uuid`,
   `step_path`, `todo_uuid`, `bug_fix_uuid`, `assigned_binding_uuid`,
   `parent_attempt_uuid`, `created_by`.
3. **FK-backed:** none — despite `plan_uuid NOT NULL` and `step_uuid NOT NULL`.
4. **Plain references:** all of the columns in facet 2, including the
   self-reference `parent_attempt_uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["execution_attempt"]` plus
   `ExecutionAttempt.HARD_DELETE_REFERENCE_CHECKS`; no dedicated
   `runtime_hard_delete.py` wrapper.
7. **Commands:** `execution_attempt_get`, `execution_attempt_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `execution_attempt`.

### review_result

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `reviewed_attempt_uuid`,
   `reviewed_revision_uuid`, `escalation_target_uuid`, `reviewer`,
   `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the columns in facet 2.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["review_result"]` plus
   `ReviewResult.HARD_DELETE_REFERENCE_CHECKS`; no wrapper.
7. **Commands:** `review_result_get`, `review_result_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `review_result`.

### escalation

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the full `anchor_*` family;
   `forwarded_from_uuid` and `chain_root_uuid` (added in `0020`);
   `resolved_by`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** every `anchor_*` identifier column, the polymorphic
   `anchor_ref_id`, and the two chain self-references from `0020`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only; no reference-check entry
   and no wrapper.
7. **Commands:** `escalation_get`, `escalation_list`, `escalation_resolve`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `escalation`.

### escalation_policy

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `created_by` only.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** none registered.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### answer_envelope

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `anchor_plan_uuid`, `anchor_step_uuid`,
   `attempt_uuid`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the columns in facet 2.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** none registered.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### runtime_link

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `from_entity_uuid`, `to_entity_uuid`, with the
   discriminators `from_entity_type` and `to_entity_type`; `created_by`.
3. **FK-backed:** none.
4. **Plain references:** `from_entity_uuid` and `to_entity_uuid` — fully
   polymorphic endpoints, each interpreted through its own type discriminator.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `runtime_link_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0016`),
   entity type `runtime_link`.

### wish_item

Entity type is `wish`; the table name is `wish_item`. The two differ.

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the full `anchor_*` family, `created_by`,
   `assigned_to`.
3. **FK-backed:** none.
4. **Plain references:** every `anchor_*` identifier column and the polymorphic
   `anchor_ref_id`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `WishItem.HARD_DELETE_REFERENCE_CHECKS` in
   `plan_manager/domain/wish.py` through `hard_delete_entity`; no wrapper.
7. **Commands:** `wish_get`, `wish_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0025`),
   entity type `wish`.

### calendar_entry

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the full `anchor_*` family, `wish_uuid`,
   `created_by`, `assigned_to`.
3. **FK-backed:** none.
4. **Plain references:** every `anchor_*` identifier column and `wish_uuid`,
   which points at `wish_item.uuid` without an FK.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `calendar_entry_get`, `calendar_entry_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0025`),
   entity type `calendar_entry`.

---

## Bug lifecycle entities

### bug_report

Entity type is `bug`; the table name is `bug_report`. The two differ.

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** the `source_*` anchor family
   (`source_anchor_type`, `source_project_id`, `source_file_path`,
   `source_plan_uuid`, `source_revision_uuid`, `source_step_uuid`,
   `source_step_path`, `source_ref_id`, `source_command`, `source_service`),
   `duplicate_of_uuid`, `parent_bug_uuid`, `reporter`, `owner`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** every `source_*` identifier column and the two
   self-references `duplicate_of_uuid` and `parent_bug_uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_bug` in `runtime_hard_delete.py`, over
   `CENTRAL_REFERENCE_CHECKS["bug"]` and
   `BugReport.HARD_DELETE_REFERENCE_CHECKS`.
7. **Commands:** `bug_get`, `bug_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `bug`.

### bug_impact

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `bug_uuid`, the `target_*` family
   (`target_type`, `target_project_id`, `target_file_path`,
   `target_plan_uuid`, `target_revision_uuid`, `target_step_uuid`,
   `target_step_path`, `target_ref_id`, `target_identifier`), `created_by`.
3. **FK-backed:** none.
4. **Plain references:** `bug_uuid` and every `target_*` identifier column.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_bug_impact` in
   `runtime_hard_delete.py`, over `CENTRAL_REFERENCE_CHECKS["bug_impact"]` and
   `BugImpact.HARD_DELETE_REFERENCE_CHECKS`.
7. **Commands:** `bug_impact_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `bug_impact`.

### bug_fix

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `bug_uuid`, `source_project_id`, `author`,
   `reviewer`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** `bug_uuid`, `source_project_id`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_bug_fix` in `runtime_hard_delete.py`,
   over `CENTRAL_REFERENCE_CHECKS["bug_fix"]` and
   `BugFix.HARD_DELETE_REFERENCE_CHECKS`.
7. **Commands:** `bug_fix_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `bug_fix`.

### bug_fix_propagation

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `bug_fix_uuid`, `impact_uuid`,
   `linked_todo_uuid`, `linked_plan_uuid`, `linked_cascade_uuid`,
   `target_identifier`, `assigned_to`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the identifier columns in facet 2.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_bug_fix_propagation` in
   `runtime_hard_delete.py`; no per-entity reference-check table.
7. **Commands:** `bug_propagation_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `bug_fix_propagation`.

### project_dependency

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `dependent_project_id`,
   `depends_on_project_id`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** both project columns hold external project UUIDs and
   cannot be FK-backed, since no local project table exists.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `project_dependency_list`, `project_dependents`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `project_dependency`.

---

## Agent-configuration entities

### provider

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `created_by`.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["provider"]` through
   `hard_delete_entity`; no wrapper.
7. **Commands:** `provider_get`, `provider_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `provider`.

### model

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `provider_uuid`, `created_by`.
3. **FK-backed:** none, despite `provider_uuid NOT NULL`.
4. **Plain references:** `provider_uuid -> provider.uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `model_get`, `model_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `model`.

### model_binding

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `branch_step_uuid`,
   `revision_uuid`, `step_uuid`, `step_path`, `role`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the identifier columns in facet 2, each
   populated only for the matching `scope` value.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `model_binding_get`, `model_binding_list`,
   `model_binding_resolve`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0015`),
   entity type `model_binding`.

### role

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `created_by`.
3. **FK-backed:** none.
4. **Plain references:** none. The `role` column of other tables holds this
   table's `name`, not its `uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `role_get`, `role_list`, `role_model_resolve`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `role`.

### role_model_binding

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `role`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** `role` holds `role.name`, a name reference rather than
   an identifier reference.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `role_model_resolve` reads it; no dedicated get/list.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### tool

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `created_by`.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `CENTRAL_REFERENCE_CHECKS["tool"]` through
   `hard_delete_entity`; no wrapper.
7. **Commands:** `tool_get`, `tool_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `tool`.

### toolset

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `created_by`.
3. **FK-backed:** none.
4. **Plain references:** none.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `toolset_get`, `toolset_list`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `toolset`.

### toolset_membership

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `toolset_uuid`, `tool_uuid`, `created_by`.
3. **FK-backed:** none, despite both columns being `NOT NULL`.
4. **Plain references:** `toolset_uuid -> toolset.uuid`,
   `tool_uuid -> tool.uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** none of its own; memberships surface through `toolset_get`.
8. **Registry:** absent from `ALLOWED_TABLES`; triggers present (`0018`),
   entity type `toolset_membership`.

### invocation_profile

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `branch_step_uuid`,
   `revision_uuid`, `step_uuid`, `step_path`, `role`, `dialogue_chain_ref`,
   `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the identifier columns in facet 2, each
   populated only for the matching `scope` value.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `invocation_profile_get`, `invocation_profile_list`,
   `invocation_profile_resolve`.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

### step_assignment

1. **Identifier:** `uuid uuid PRIMARY KEY`.
2. **Owner/reference columns:** `plan_uuid`, `branch_step_uuid`,
   `revision_uuid`, `step_uuid`, `step_path`, `role`, `assigned_role`,
   `toolset_uuid`, `created_by`.
3. **FK-backed:** none.
4. **Plain references:** all of the identifier columns in facet 2, including
   `toolset_uuid -> toolset.uuid`.
5. **Soft delete:** `deleted_at timestamptz NULL`.
6. **Hard-delete path:** `hard_delete_entity` only.
7. **Commands:** `step_assignment_resolve`; no dedicated get/list.
8. **Registry:** absent from `ALLOWED_TABLES`; no triggers.

---

## Summary matrix

`SD` = soft-delete column present. `FK` = table declares at least one foreign
key. `Trig` = identity-registry triggers present. `AT` = member of
`identity.py` `ALLOWED_TABLES`. `HD` = hard-delete path: `W` a
`runtime_hard_delete.py` wrapper, `R` a reference-check table entry consumed by
`hard_delete_entity`, `B` the entity base only, `-` none of its own (cascade or
append-only). `Cmd` = at least one registered read command.

| Table | SD | FK | Plain refs | HD | Cmd | Trig | AT |
|---|---|---|---|---|---|---|---|
| plan | yes | yes | yes | R | yes | yes | yes |
| paragraph | no | yes | no | B | yes | yes | yes |
| concept | no | yes | no | R | yes | yes | yes |
| relation | no | yes | yes | B | yes | yes | yes |
| step | no | yes | yes | R | yes | yes | yes |
| step_runtime | no | yes | no | - | yes | no | no |
| node_version | no | yes | yes | - | no | yes | yes |
| revision | no | yes | yes | - | no | yes | yes |
| ref | no | yes | no | - | no | yes | yes |
| cascade | no | yes | no | - | yes | yes | no |
| cascade_request | no | yes | yes | - | no | yes | no |
| context_block | no | yes | yes | - | yes | yes | no |
| srt_snapshot | no | yes | no | - | yes | yes | no |
| runtime_audit_log | no | yes | yes | - | yes | yes | no |
| command_metric | no | no | no | - | yes | no | no |
| embedding_cache | no | no | no | - | no | no | no |
| entity_identity | no | no | yes | - | no | no | no |
| todo_item | yes | no | yes | W | yes | yes | no |
| todo_link | yes | yes | no | - | yes | yes | no |
| runtime_comment | yes | no | yes | W | yes | yes | no |
| execution_attempt | yes | no | yes | R | yes | yes | no |
| review_result | yes | no | yes | R | yes | yes | no |
| escalation | yes | no | yes | B | yes | yes | no |
| escalation_policy | yes | no | no | B | no | no | no |
| answer_envelope | yes | no | yes | B | no | no | no |
| runtime_link | yes | no | yes | B | yes | yes | no |
| wish_item | yes | no | yes | R | yes | yes | no |
| calendar_entry | yes | no | yes | B | yes | yes | no |
| bug_report | yes | no | yes | W | yes | yes | no |
| bug_impact | yes | no | yes | W | yes | yes | no |
| bug_fix | yes | no | yes | W | yes | yes | no |
| bug_fix_propagation | yes | no | yes | W | yes | yes | no |
| project_dependency | yes | no | yes | B | yes | yes | no |
| provider | yes | no | no | R | yes | yes | no |
| model | yes | no | yes | B | yes | yes | no |
| model_binding | yes | no | yes | B | yes | yes | no |
| role | yes | no | no | B | yes | yes | no |
| role_model_binding | yes | no | yes | B | yes | no | no |
| tool | yes | no | no | R | yes | yes | no |
| toolset | yes | no | no | B | yes | yes | no |
| toolset_membership | yes | no | yes | B | no | yes | no |
| invocation_profile | yes | no | yes | B | yes | no | no |
| step_assignment | yes | no | yes | B | yes | no | no |

Counts read off the matrix: 43 tables; 26 carry `deleted_at`; 15 declare at
least one foreign key and 28 declare none; 34 carry identity-registry triggers;
8 are members of `ALLOWED_TABLES`; 6 have a `runtime_hard_delete.py` wrapper;
9 have a reference-check table entry; 37 have at least one registered read
command and 6 have none.

## Tables absent from the identity registry

Nine tables carry no `entity_identity` registration triggers:

| Table | Note |
|---|---|
| step_runtime | Keyed by `step_uuid`, not an independent identifier. |
| command_metric | Append-only timing log. |
| embedding_cache | Content-addressed cache keyed by `content_hash`. |
| entity_identity | The registry itself. |
| escalation_policy | Added in `0020`; no trigger block was written. |
| answer_envelope | Added in `0020`; no trigger block was written. |
| role_model_binding | Added in `0019`; no trigger block was written. |
| invocation_profile | Added in `0019`; no trigger block was written. |
| step_assignment | Added in `0019`; no trigger block was written. |

Separately, twenty-six tables carry registration triggers but are absent from
the Python `ALLOWED_TABLES` guard: `bug_fix`, `bug_fix_propagation`,
`bug_impact`, `bug_report`, `calendar_entry`, `cascade`, `cascade_request`,
`context_block`, `escalation`, `execution_attempt`, `model`, `model_binding`,
`project_dependency`, `provider`, `review_result`, `role`, `runtime_audit_log`,
`runtime_comment`, `runtime_link`, `srt_snapshot`, `todo_item`, `todo_link`,
`tool`, `toolset`, `toolset_membership`, `wish_item`.

The database therefore already registers 34 tables while the Python guard
admits 8. Both statements are facts about the shipped code; reconciling them is
the subject of the companion document `identity_reconciliation.md`.

A note on how `cascade` is easy to miss: its triggers are written against the
quoted identifier `"cascade"`, because the word is reserved. A survey that
matches `ON (\w+)` skips them and undercounts the registry by one.
