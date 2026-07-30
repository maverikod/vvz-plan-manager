# CR-6 audit coverage matrix

- **Plan:** `planmgr-cr6-entity-identity-crud`
- **Concept:** C-016 CompatibilityAndAuditContract
- **Purpose:** map every mutating surface CR-6 adds to its audit-trail
  contract — the `record_runtime_change` call it must make, the
  `ALLOWED_ACTIONS` value it uses, and the `DOMAIN_CODES` entries it advertises.

Produced by G-005/T-002/A-001. This document is normative: it drives the
regression suite `tests/test_cr6_compat_audit_contract.py` and the post-deploy
verification.

## Baselines

`ALLOWED_ACTIONS` before CR-6 (13 values, `plan_manager/storage/runtime_audit_store.py`):
`create`, `update`, `soft_delete`, `hard_delete`, `archive`, `restore`,
`plan_unfreeze`, `subtree_unfreeze`, `cascade_begin`, `cascade_commit`,
`cascade_abort`, `plan_completed_set`, `plan_comment_set`.

**Actions CR-6 adds (2):** `project_uuid_reserve` and `project_uuid_release`,
registered by G-002/T-003/A-006. The vocabulary is now 15 values. This
registration is mandatory rather than cosmetic: `record_runtime_change`
validates its `action` argument against the set and rejects anything
unregistered, so the reservation command would raise on its first successful
reserve without it.

`DOMAIN_CODES` before CR-6: 91 codes, with no `RESERVATION`-prefixed member.
**Codes CR-6 adds (1):** `RESERVATION_NOT_FOUND`, registered by
G-002/T-003/A-007. The vocabulary is now 92.

Command inventory: 211 names, 73 of them mutating. CR-6 adds three commands —
`project_uuid_reserve` (shipped), `runtime_purge_batch` and `reference_inspect`
(G-004).

## The matrix

| Surface | Command(s) | Action (from ALLOWED_ACTIONS) | Entity Type | Error Codes | Gate/Notes |
|---|---|---|---|---|---|
| Identity registration | every create path via `DataclassEntity.crud_create` | none of its own | the created entity's `ENTITY_TYPE` | `DUPLICATE_ID` | Not separately audited. The registry row is a side effect of the entity INSERT, and the create path's own `create` audit already records the event. Gated by `ensure_identity_available` BEFORE the INSERT, so a collision leaves no partial row. Skipped for `EXCLUDED_TABLES`. |
| Namespace reservation | `project_uuid_reserve` (action=reserve) | `project_uuid_reserve` | `project_uuid_reservation` | `DUPLICATE_ID`, `RUNTIME_VALIDATION_ERROR` | Exactly one audit row on success. A colliding reserve writes NO audit: nothing changed, so there is nothing to record. `plan_uuid` is passed explicitly as `None` — a reservation is a namespace record, not plan-anchored truth. |
| Reservation release | `project_uuid_reserve` (action=release) | `project_uuid_release` | `project_uuid_reservation` | `RESERVATION_NOT_FOUND`, `RUNTIME_VALIDATION_ERROR` | One audit row on success; none when the reservation is absent. The DELETE is scoped to `kind='project_reservation'`, so release can never strip identity from a live entity. |
| Reservation resolve | `project_uuid_reserve` (action=resolve) | none | — | `RESERVATION_NOT_FOUND` | A read. Never audits. An identifier registered as an ordinary entity resolves to `RESERVATION_NOT_FOUND` rather than being reported as a reservation. |
| Entity soft delete | the per-entity `*_delete` commands via `perform_runtime_delete` | `soft_delete` | the entity's `ENTITY_TYPE` | the entity's `*_NOT_FOUND` code | Pre-existing surface, unchanged by CR-6. Recorded here for completeness because the matrix must cover the whole deletion lifecycle. |
| Entity hard delete | the same `*_delete` commands with `hard=true`; `runtime_hard_delete` wrappers | `hard_delete` | the entity's `ENTITY_TYPE` | `DELETE_BLOCKED` | G-004 makes the guard the SINGLE audit point and strips the six wrappers' own audit writes, so one deletion yields exactly one audit row rather than two. |
| Hard-delete refusal | the same surfaces, when a blocking reference exists | `hard_delete` with `changed_fields.refused=true` | the entity's `ENTITY_TYPE` | `DELETE_BLOCKED` | New in CR-6: refusals were previously never audited at all. Reuses the existing `hard_delete` action rather than adding one, so the vocabulary does not grow. Every identifier in `changed_fields` is stringified, because the audit store wraps the payload in a `Jsonb` adapter that cannot encode `uuid` objects. |
| Batch purge | `runtime_purge_batch` | `hard_delete` (written by the guard beneath) | the purged entity's `ENTITY_TYPE` | `DELETE_BLOCKED`, `RUNTIME_VALIDATION_ERROR` | The command and `purge_soft_deleted_batch` write NO audit of their own; they thread `changed_by` down so the guard's record names the batch actor. A local audit write here would double-count every purged row. |
| Reference inspection | `reference_inspect` | none | — | `RUNTIME_VALIDATION_ERROR`, `INVALID_PAGINATION` | Read-only. Never audits. Absent from `MUTATING`. |

## Invariants the matrix asserts

1. **Every action value in the Action column is a member of `ALLOWED_ACTIONS`.**
   A surface that needs a new action registers it before it can write.
2. **Every code in the Error Codes column is a member of `DOMAIN_CODES`**, and,
   by the pre-existing reachability contract, is advertised in at least one
   command's `error_cases`. The two constraints are mutually dependent: a new
   code and the command advertising it must land together, because neither
   ordering is green in between.
3. **A refused mutation writes no audit row, except for a hard-delete refusal,**
   which is audited deliberately under the existing `hard_delete` action with
   `refused=true` in `changed_fields`. Everywhere else, nothing changed, so
   nothing is recorded.
4. **A mutation is audited exactly once.** Where a lower layer already audits,
   the upper layer must not audit again. CR-6 enforces this in two places: the
   six `runtime_hard_delete` wrappers lose their own writes when the guard
   takes over, and the batch purge threads the actor down instead of recording
   locally.
5. **`changed_fields` is JSON-serializable.** `record_runtime_change` wraps it
   in `Jsonb`, which cannot encode a `uuid`, so every identifier is converted
   to `str` before it is embedded.
6. **The vocabularies are append-only.** No action value and no domain code is
   ever removed or renamed, because recorded audit rows and client error
   handling keep referring to them.
