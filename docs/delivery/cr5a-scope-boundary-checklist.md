# CR-5a Scope Boundary Checklist

## Excluded Consumers

CR-5a (plan `planmgr-cr5a-agent-config-data-layer`) does not ship the following 11 items. These items represent consumers of the CR-5a data layer that are excluded from this change request and deferred to future or sibling work:

- the coordinator and its sweep loop
- the message-bus runtime
- the tool-call emulation loop
- workplace-binding runtime
- the dialogue-chain service
- knowledge-base injection
- the context optimizer
- the prompt entity layer (this is CR-5b, a sibling/follow-on change request — not this one)
- the change-request entity (CR-5a's own change-request domain entity — CR-5a itself is a change request, but it does not ship a "change request" entity in its data layer)
- automatic model ratings (deferred to a later change request)
- any ENFORCEMENT of invocation-profile values (CR-5a stores/persists invocation-profile records as data, but does not enforce or apply their values at runtime)

## Consumption Invariant

Each of the 11 excluded items above consumes the CR-5a data layer—it would read and use the entities and command surface that CR-5a ships. However, none of these 11 items ship as part of CR-5a itself. This boundary is deliberate: it represents a consumption relationship, not a scope gap. The excluded items are future or sibling work that builds on top of the CR-5a data layer.

## Verification

### Git-diff baseline

Verification is performed via `git diff` against the pre-CR-5a baseline, confirming that no code module implementing any of the 11 excluded items was added.

### Live-catalog diff

Verification is additionally performed by running the `command_catalog_dump` command against the deployed instance and diffing the result against a pre-CR-5a baseline catalog, confirming that no new command surface introduced by CR-5a corresponds to any of the 11 excluded items.
