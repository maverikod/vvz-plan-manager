# CR-6 Governance Closure and Release-Checkpoint Procedure

## Purpose

This document records the governance state under which change request CR-6
("Centralize entity identity, references, CRUD, and deletion lifecycle", todo
`558cd81a`, plan `planmgr-cr6-entity-identity-crud`) closes: the impact review
that cleared it against every other live plan, its ordering against the next
initiative, and the gate that must pass before its roadmap todo is closed.

It follows the checkpoint structure of
`docs/delivery/cr5a-delivery-closeout-checkpoints.md` and defers every
operational detail to `docs/delivery/cr6-acceptance-procedure.md`.

## 1. Impact-review dispositions (2026-07-29)

The review examined every plan live in the Plan Manager service at that date and
recorded the following dispositions.

### 1.1 Seven completed plans — unaffected

CR-1, CR-2, CR-3, CR-4, CR-5, CR-5a, `runtime-work-layer-integration` and
`semantic-reproduction-tree` are shipped work. Their runtime overlays participate
in CR-6 only as **migration data**: rows the identity backfill registers and the
reference catalog describes. No frozen artifact of any completed plan is read,
rewritten, or reinterpreted by this change request. Disposition: unaffected.

### 1.2 The open roadmap plan — unaffected

`planmgr-post-runtime-roadmap` carries no executable branches, so there is
nothing in it for CR-6 to invalidate. This plan
(`planmgr-cr6-entity-identity-crud`) realizes its `2m4m` successor paragraph.
Disposition: unaffected.

### 1.3 External-project plans — structurally unaffected

Plans belonging to other projects (lmrs, doc-store, science-assistant, workmgr and
the rest) are consumers of the plan-manager service, not of its internals. CR-6
changes who owns identity registration, reference lookup and deletion admission
inside the service; the command contracts those plans call are preserved, and the
one behaviour change (`todo_link.from_todo_uuid` no longer blocking a todo
deletion, because it is `ON DELETE CASCADE` and the retired per-entity check was
over-strict) makes previously refused deletions succeed rather than the reverse.
Disposition: structurally unaffected consumers.

### 1.4 Smoke litter — purged

Five throwaway plans left behind by earlier live-smoke runs were hard-deleted, and
one dangling cascade was aborted. Litter is purged rather than tolerated: a
throwaway plan left in the service is indistinguishable from real work to every
later inventory query, including CR-6's own identity backfill.

### 1.5 Five open cascades — tolerated, not force-closed

The remaining open cascades belong to `lmrs`, `doc-store`,
`science-assistant-ephemeris-apis`, `doc-store-redis-read-projection` and
`workmgr`. They are **tolerated** under the migration-discipline paragraph rather
than force-closed.

Force-closing another project's open cascade would commit work its owner has not
finished, and CR-6 has no standing to do that. The migration-discipline rules in
`docs/delivery/cr6-migration-discipline.md` are written so that an open cascade is
a legal state a migration must survive, not an obstacle a migration may remove:
migration `0026_identity_registry_full_scope.sql` is additive and idempotent, and
its backfill is deliberately not reversed on rollback precisely so that a cascade
open across the migration boundary stays coherent.

## 2. Initiative ordering

By owner decision of 2026-07-29, this plan **precedes** the execution-integrity
initiative (todo `a78e24e0`).

CR-6 hands that initiative two pieces of groundwork:

- the **identity registry** at full scope (39 admitted tables, 4 documented
  exclusions, reservations as first-class registry entries), which gives
  execution-integrity a single authority for "does this identifier exist and what
  holds it";
- the **reference catalog** and the central hard-delete guard, which give it a
  single authority for "what points at this, and would removing it be refused".

**The handoff does not gate this plan's own closure.** CR-6 closes on its own
acceptance evidence. Whether the execution-integrity initiative consumes this
groundwork well, badly, or at all is a matter for that initiative's own plan;
making CR-6's closure wait on it would couple two independently deliverable
bodies of work for no verification benefit.

## 3. Closure gate for todo 558cd81a

### 3.1 Plan-first delivery discipline

The discipline binds throughout: **nothing in this plan authorizes implementation
outside its own artifacts.** Work that turns out to be necessary but is not
described by a frozen atomic step is added to the plan by amendment
(`plan_unfreeze` → cascade → author → freeze) before it is written, not written
first and documented after. Where a step's instruction was followed with a
deliberate deviation — a module name the registry's own resolution convention
forced, a fixture hop the reference classification made impossible — the
deviation is recorded at the site in the code it affects, so the divergence
between plan and artifact is discoverable from either end.

### 3.2 Hard checkpoints

Two checkpoints are taken **only on the user's explicit order**, never inferred
from a green gate, from passing tests, or from a previously taken checkpoint:

1. **Plan freeze** — the plan's frozen artifacts become the immutable input to
   execution.
2. **Production deploy** — the built artifact goes to the deployment target.

If the order for a checkpoint has not been given, that checkpoint and everything
after it remain blocked.

### 3.3 The gate itself

Todo `558cd81a` is closed **only** after the full acceptance battery of
`docs/delivery/cr6-acceptance-procedure.md` passes fully green on the deployed
server: every named `pipeline` check including the four `cr6-*` slice checks, and
`live_smoke.py` green at the exact deployed version with R33
(`project_uuid_reserve`) and R34 (`reference_inspect`) both `PASS` rather than
`SKIP`, plus the slice-specific live evidence that document enumerates.

The `todo_close` call MUST supply its `execution_result` parameter referencing
that verified release. A todo closed without an `execution_result` reference has
not completed this procedure: the reference is what makes the closure auditable
later, when the only surviving record of why the todo was closed is the todo
itself.
