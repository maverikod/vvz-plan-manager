# Dead-code triage

Produced by G-001/T-002/A-001 of plan `planmgr-cr6-entity-identity-crud`.

Starting point: todo `7fcda2a9-70c9-4710-8248-9c78fc2e5117`, "Triage 57 dead-code
candidates from CA analysis (EntityRecord/crud_*, legacy_* handlers, unwired
soft_delete ops)", recorded 2026-07-23 against a Code Analysis
`analyze_tree mode=dead_code` run that reported 135 unused symbols, of which 78
were judged false positives (`*Command` classes reached through adapter
dispatch), leaving 57 for manual triage.

## Refreshed evidence

The evidence below is **not** the 2026-07-23 run. A fresh sweep was executed
against the live Code Analysis project `f06b7269-cc9c-4293-886b-24984e4033ba`
for this document. The sweep rebuilt its usage index first — the staleness block
reports `rebuilt: 511`, `sha_match: 1`, `not_in_db: 36` — so the classification
reflects current code, not the July index.

Fresh sweep totals: 2206 symbols, 1873 live, 190 unused, 93 test-only,
50 import-only, 333 "removable". These numbers supersede the 135/78/57 split
recorded in the todo; the codebase has moved by roughly 0.1.61 → 0.1.87 since.

**Every Code Analysis classification below was re-verified against the
repository before it was accepted.** That verification changed the verdict for
nine of the sixteen named candidates. Code Analysis attributes usage by symbol
name and misses three reference forms present in this codebase: class
inheritance, a function passed as a callable argument, and a Pydantic
`default_factory`. Each such symbol is reported `unused` by the tool and is in
fact live.

---

## Named candidates from the todo

### 1. `EntityRecord` — `plan_manager/domain/entity.py`

- **Tool verdict:** unused.
- **Repository evidence:** `plan_manager/domain/entity.py:201` declares
  `class DataclassEntity(EntityRecord)`. Five further mentions in
  `commands/list_projection.py` and `commands/project_view_command.py` are
  documentation prose. Two test references exist.
- **Verified verdict:** LIVE. The tool misses inheritance. The todo's own
  caution — that the 8a13977d fix newly consumes `SUMMARY_FIELDS` and
  `to_summary_payload` — is confirmed correct.
- **Decision: wire.** `EntityRecord` is the summary-projection half of the base
  contract and becomes part of the centralized entity surface.
- **Executing goal:** G-003.

### 2. `DataclassEntity.crud_create` — `plan_manager/domain/entity.py`

- **Tool verdict:** unused.
- **Repository evidence:** zero references outside its own definition, in
  production or in tests.
- **Verified verdict:** genuinely unconsumed.
- **Decision: wire.** The method is correct and becomes the single create path
  once the per-store SQL is retired; G-002 additionally adds the identity
  pre-check and post-registration to it.
- **Executing goal:** G-002 (identity hooks), G-003 (store rerouting).

### 3. `DataclassEntity.crud_search` — `plan_manager/domain/entity.py`

- **Tool verdict:** unused.
- **Repository evidence:** zero references anywhere.
- **Verified verdict:** genuinely unconsumed. It is additionally a pure alias of
  `crud_list`: it accepts the same filters and never reads `SEARCH_COLUMNS`.
- **Decision: replace.** The alias body is replaced by a real substring and
  regex implementation over declared `SEARCH_COLUMNS`.
- **Executing goal:** G-003.

### 4. `DataclassEntity.crud_resolve_identity` — `plan_manager/domain/entity.py`

- **Tool verdict:** unused.
- **Repository evidence:** zero references anywhere.
- **Verified verdict:** genuinely unconsumed.
- **Decision: wire.** It is the base-level accessor over the identity registry
  and is consumed by the reference-inspection surface.
- **Executing goal:** G-004.

### 5-7. `legacy_get_methods_get`, `legacy_get_methods_post`, `legacy_jsonrpc` — `plan_manager/main.py`

- **Tool verdict:** unused (all three).
- **Repository evidence:** zero references anywhere, production or test.
- **Verified verdict:** genuinely dead legacy transport handlers.
- **Decision: delete.** No consumer, no role; the adapter serves the JSON-RPC
  surface.
- **Executing goal:** none in this plan. These are transport handlers, outside
  the entity-identity/CRUD/deletion scope, and deleting them here would widen
  the plan. Recorded as an unresolved-by-scope item below.

### 8. `revert_bug_fix` — `plan_manager/storage/bug_fix_store.py`

- **Tool verdict:** unused.
- **Repository evidence:** zero references anywhere.
- **Verified verdict:** genuinely unconsumed. It is a raw-SQL UPDATE with no
  command exposing it.
- **Decision: wire.** It is a legitimate lifecycle operation with no surface,
  not dead weight; the G-003 store migration leaves it in place explicitly and
  documents it as unexposed rather than silently deleting a working path.
- **Executing goal:** G-003 (documented as retained-and-unexposed).

### 9-12. `soft_delete_bug`, `soft_delete_bug_fix`, `soft_delete_bug_impact`, `soft_delete_bug_fix_propagation` — bug stores

- **Tool verdict:** unused (all four).
- **Repository evidence:** each is imported by its delete command and passed as
  a callable into the shared lifecycle helper. For example
  `plan_manager/commands/bug_delete_command.py:17` imports `soft_delete_bug` and
  line 70 passes `soft_delete=soft_delete_bug`. Each also carries test
  references.
- **Verified verdict:** LIVE. The tool misses a function passed as an argument.
  The todo's hypothesis that these are "possibly unwired admin ops" is
  **refuted**.
- **Decision: replace.** They are live and correct, and the G-003 migration
  reroutes each through `crud_soft_delete` while keeping the public signature.
- **Executing goal:** G-003.

### 13-16. `DatabaseSection`, `EmbeddingSection`, `CodeAnalysisSection`, `ScoringSection` — `plan_manager/runtime/config.py`

- **Tool verdict:** unused (all four).
- **Repository evidence:** each is used as a Pydantic field factory or
  annotation, e.g. `plan_manager/runtime/config.py:150`
  `scoring: ScoringSection = Field(default_factory=ScoringSection)`.
- **Verified verdict:** LIVE. The tool misses `default_factory` construction.
  The todo predicted this false-positive class; it is confirmed.
- **Decision: keep as-is.** No action.
- **Executing goal:** none required.

---

## Remaining unused symbols, by category

The fresh sweep's 190 unused symbols beyond the named sixteen fall into four
categories. Each category carries one decision; individual symbols are not
enumerated where the decision is uniform and evidence-backed.

### A. Never-wired store families — 15 symbols, decision: **wire**, goal G-003

`plan_manager/storage/answer_envelope_store.py` (`create_answer_envelope`,
`get_answer_envelope`, `list_answer_envelopes`),
`escalation_policy_store.py` (`create_escalation_policy`,
`get_escalation_policy`, `get_active_escalation_policy`,
`list_escalation_policies`),
`role_model_binding_store.py` (`create_role_model_binding`,
`list_role_model_bindings`, `update_role_model_binding`,
`remove_role_model_binding`),
`step_assignment_store.py` (`create_step_assignment`, `list_step_assignments`,
`update_step_assignment`, `remove_step_assignment`).

This category cross-confirms an independent finding of `schema_inventory.md`:
these four tables are exactly the four ordinary identified, soft-deletable
tables that carry **no identity-registry triggers and no registered read
command**. Three facts — no trigger, no command, no caller — point at the same
gap from three directions. The stores exist and work; nothing reaches them.

### B. Identity module helpers — 2 symbols, decision: **wire**, goal G-002

`plan_manager/storage/identity.py`: `new_entity_uuid`, `resolve_scoped_name`.
Both are part of the identity contract G-002 extends to full scope.

### C. Version-store primitives — 2 symbols, decision: **keep as-is**

`plan_manager/storage/version_ops.py`: `log`, `revert`. These belong to the
immutable content-addressed DAG, which `schema_inventory.md` records as having
no registered command surface by design. G-003 explicitly documents the version
primitives as out of the common-entity-contract scope, so they are not dead
code awaiting removal.

### D. Config validators and assorted single symbols — the remainder, decision: **unresolved**

`plan_manager/runtime/config.py` (`check_host_xor_socket`,
`check_aggregation`, `check_embedding_serialization`) are almost certainly
Pydantic validators reached by decorator registration, the same false-positive
class as category 13-16, but this was not verified symbol by symbol. The
remaining single-symbol entries across `views/`, `verify/`, and the domain
modules were not individually triaged.

---

## Summary counts by decision

| Decision | Named candidates | Categorical | Total |
|---|---|---|---|
| wire | 4 (`EntityRecord`, `crud_create`, `crud_resolve_identity`, `revert_bug_fix`) | 17 (A: 15, B: 2) | 21 |
| replace | 5 (`crud_search`, four `soft_delete_*`) | 0 | 5 |
| delete | 3 (three `legacy_*` handlers) | 0 | 3 |
| keep as-is | 4 (four config `*Section` classes) | 2 (C) | 6 |
| unresolved | 0 | see below | see below |

Sixteen named candidates were fully resolved with refreshed evidence. Nine of
them — `EntityRecord`, the four `soft_delete_*` functions, and the four config
`*Section` classes — were **false positives**, which is the single most
important result of this refresh: the tool's unused list cannot be acted on
without per-symbol repository verification.

## Candidates that could not be resolved with evidence

1. **The three `legacy_*` transport handlers in `plan_manager/main.py`.**
   Evidence is conclusive that they are dead, but no goal of this plan owns
   `main.py`. Deleting them here would widen the plan beyond entity identity,
   CRUD, and deletion. They need a separate cleanup task.

2. **Category D**, the config validators and the assorted single-symbol
   entries across `views/`, `verify/`, and several domain modules. These were
   not verified symbol by symbol in this pass. The count is the fresh sweep's
   190 unused symbols minus the 16 named candidates, minus category A's 15,
   B's 2 and C's 2 — that is **155 symbols still untriaged**.

3. **The 93 test-only and 50 import-only symbols** were not triaged at all.
   Neither classification means dead, and neither is in this plan's scope.

The original todo's framing of "57 candidates" no longer matches the codebase:
the fresh sweep reports 190 unused symbols. Todo `7fcda2a9` should be updated
with these figures rather than closed on the basis of this document, because
155 of its successors remain untriaged.
