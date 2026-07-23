# CR-5a Template Substrate

## System position (HRS {61ud})

A frozen plan_manager plan is a **STATIC TEMPLATE** — the analog of an ordinary API,
stretched out over time. It does not run; it is read. At execution time, an external
coordinator hands each assembled prompt (the deterministic executor prompt for one
branch, or a frozen atomic-step prompt) to a **context-preparer model**, which mixes in
additional information the template itself cannot contain — dialogue slices from the
running conversation, knowledge-base excerpts, and reality supplements describing the
current state of the repository or environment — before that enriched prompt is
dispatched to a worker for execution.

This is the same relationship an ordinary HTTP API has with its caller: the API defines
stable, typed endpoints and payload shapes; the caller supplies the request-specific data
at call time. plan_manager's frozen plan plays the role of the API definition. The
context-preparer plays the role of the calling application, populating each call with
live, request-specific content the API definition itself never carries.

CR-5a's job is not to build that context-preparer or its enrichment pipeline. CR-5a's job
is to supply the **declarative substrate** this template mechanism needs in order to have
something stable to bind to: stable entity references, profile records, and typed record
shapes. Enrichment binds to these references; it does not replace them, and it is not
part of them.

## What CR-5a ships as the substrate (HRS {gfrf})

CR-5a realizes the substrate as one thing: the documented **entity command surface**
(C-015) — the uniform CRUD, list, and resolve command family already registered in the
command catalog (`plan_manager.commands.inventory.INVENTORY`) and already gated by the
same mutation, audit, and soft-delete-with-integrity discipline as every other command in
this codebase. Every new entity ships uniform create/read/update/list commands with the
catalog's standard filtering and pagination; every mutation writes a runtime audit
record; deletion is soft by default and gated by the inbound-reference integrity
discipline already used by the runtime layer (`plan_manager.domain.entity.
CENTRAL_REFERENCE_CHECKS`). Three read-only resolve commands (role-model resolution,
per-step assignment resolution, invocation-profile resolution) follow the existing
`model_binding_resolve` pattern.

No separate runtime is shipped for the substrate itself: there is no coordinator, no
message-bus loop, no tool-call emulation, and no context optimizer inside this plan (HRS
{advm}). The substrate is fully satisfied by the stable typed shapes already exposed
through this one documented command surface. The three concrete binding points enrichment
attaches to are:

1. **The entity command surface itself (C-015).** The create/read/update/list/delete
   commands for tool (C-001), toolset (C-002), role (C-003), provider (C-004), and model
   (C-005), plus the invocation-profile commands (C-008) and the three resolve commands,
   are the stable, versioned, catalog-discoverable API a context-preparer or any other
   external caller uses to look up WHO executes a step, WITH WHAT instruments, and ON
   WHICH model. This is the "ordinary API" side of the analogy in HRS {61ud}: a fixed set
   of named operations with fixed input/output shapes that do not change between calls,
   exactly like the rest of a stretched-out-over-time template plan.

2. **The invocation profile record shape (C-008) as the binding surface for call
   characteristics.** An invocation profile is a stored, purely informational record of
   call characteristics beyond the model itself — generation parameters, reasoning
   effort/budget, context-window budget, timeout, retry policy, concurrency and rate
   hints, response-format flag with optional schema, maximum tool iterations, per-call
   timeout, execution mode, per-step token/cost budget declarations, and a reserved
   dialogue-chain reference. It attaches along the same binding-scope ladder as model
   bindings (system, plan, level, branch, step, role) and resolves with the same
   specificity rules. Nothing in CR-5a enforces these values; a context-preparer or
   dispatcher reads the resolved profile through `invocation_profile_resolve` and applies
   it when shaping the enriched call it sends onward.

3. **The answer-envelope typed record shapes (C-010) as the typed enrichment-and-dispatch
   exchange.** The answer envelope is the stored discriminated answer form of a batch
   call: a discriminated union of exactly three forms — RESULT, ESCALATION, or TOOL_CALL —
   each a typed record payload carrying a schema version. CR-5a defines and stores these
   record shapes; it does not produce or consume them. They are the typed contract a
   context-preparer's dispatch and a worker's reply exchange over, in the same sense that
   a request/response schema is the typed contract of an ordinary API call.

## What stays explicitly outside this plan

The enrichment pipeline itself — the context-preparer model, the logic that selects which
dialogue slices or knowledge-base excerpts to mix in, the sweep/dispatch loop that
consumes escalation and answer-envelope records, and any coordinator or message-bus
runtime — is explicitly **outside CR-5a** (HRS {61ud}, {advm}). CR-5a's scope ends at
shipping the declarative substrate: the stable entity references, the invocation-profile
record shape, and the answer-envelope record shapes, all exposed through the documented,
catalog-registered command surface. Building the thing that reads this substrate and
performs the enrichment is the job of other plans and projects, per the approved slicing
decision recorded in HRS {advm}.

## Summary

| Substrate element | Concept | Realized as |
|---|---|---|
| Stable entity references | C-015 (Entity Command Surface) | CRUD/list/resolve commands over tool, toolset, role, provider, model, invocation profile — registered in `plan_manager.commands.inventory.INVENTORY` |
| Call-characteristic binding surface | C-008 (Invocation Profile) | The invocation-profile record shape and its `invocation_profile_resolve` command |
| Typed enrichment/dispatch exchange | C-010 (Answer Envelope) | The RESULT / ESCALATION / TOOL_CALL discriminated typed record shapes, versioned |
| Overall system position | C-017 (Template Substrate) | This document — the frozen-plan-as-static-template framing and the three binding points above |

No separate runtime, service, or process is introduced by this document or by C-017: the
substrate is fully satisfied by the stable typed shapes already exposed through the
command surface described above.
