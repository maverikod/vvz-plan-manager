# CR-5a Command Surface Reference

This document records the command surface delivered by change request CR-5a (plan `planmgr-cr5a-agent-config-data-layer`), which realizes MRS concept C-015 (Entity Command Surface); the companion document `docs/delivery/cr5a-scope-boundary-checklist.md` records what CR-5a excludes.

## Entity Command Families

CR-5a delivers six new entities, each with the same uniform command family:

### Tool

The tool entity ships with:
- A create command that persists a new tool record and returns it.
- A read command that fetches one tool record by identifier.
- An update command that patches the tool's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — a tool still referenced by another record cannot be silently removed.

### Toolset

The toolset entity ships with:
- A create command that persists a new toolset record and returns it.
- A read command that fetches one toolset record by identifier.
- An update command that patches the toolset's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — a toolset still referenced by another record cannot be silently removed.

### Role

The role entity ships with:
- A create command that persists a new role record and returns it.
- A read command that fetches one role record by identifier.
- An update command that patches the role's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — a role still referenced by another record cannot be silently removed.

### Provider

The provider entity ships with:
- A create command that persists a new provider record and returns it.
- A read command that fetches one provider record by identifier.
- An update command that patches the provider's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — a provider still referenced by another record cannot be silently removed.

### Model

The model entity ships with:
- A create command that persists a new model record and returns it.
- A read command that fetches one model record by identifier.
- An update command that patches the model's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — a model still referenced by another record cannot be silently removed.

### Invocation Profile

The invocation_profile entity ships with:
- A create command that persists a new invocation_profile record and returns it.
- A read command that fetches one invocation_profile record by identifier.
- An update command that patches the invocation_profile's mutable declarative fields.
- A list command that returns a paginated page using the catalog's standard filters plus an include-deleted flag, with total/limit/offset.
- A delete command that is soft by default and gated by inbound-reference integrity — an invocation_profile still referenced by another record cannot be silently removed.

The invocation_profile entity attaches along a six-scope binding ladder (system, plan, level, branch, step, role), the same way model bindings do. The other five entities (tool, toolset, role, provider, model) are the plan's core entities.

## Mutation Audit Logging

Every create, update, and delete (soft-delete) operation across all six entity families records a runtime audit entry naming the actor who performed it.

## Resolve Commands

CR-5a delivers two new read-only commands following the pattern already established by the existing `model_binding_resolve` command:

### Role-Model Resolution Command

A role-model resolution command reports the effective model of the required level selected from the active providers for a resolution target, following the fixed resolution order: explicit model binding, then step-level requirement, then role default. It returns the winning binding together with the full inheritance path of applicable candidates considered. This command is read-only and mutates no data.

### Invocation-Profile Resolution Command

An invocation-profile resolution command reports the winning invocation profile by the same specificity rules for a target on the six-scope binding ladder (system, plan, level, branch, step, role). It returns the inheritance path showing how the resolution was determined. This command is read-only and mutates no data.

## Authoritative Command Names

This document does not enumerate literal command-name strings. The authoritative live list of exact command names is obtained by running the `command_catalog_dump` command against the deployed instance. This document is the narrative and structural reference, not the exact-name source of truth.
