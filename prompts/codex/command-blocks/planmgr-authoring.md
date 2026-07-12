# Block ID: planmgr-authoring

Server:
- `planmgr`

Use for:
- Plan writing and mutation
- Parent/child authoring context compilation

Confirmed command group:
- `plan_create`, `plan_list`, `plan_status`
- `hrs_import`, `hrs_export`
- `concept_list`, `concept_add`, `concept_update`, `concept_remove`
- `relation_list`, `relation_add`, `relation_remove`
- `step_create`, `step_update`, `step_move`, `step_delete`, `step_tree`, `step_get`
- `step_transition`, `step_set_status`
- `cascade_begin`, `cascade_preview`, `cascade_commit`, `cascade_abort`
- `context_common`, `context_specific`, `context_bundle`, `block_get`, `block_list`

Confirmed laws:
- Plan truth lives in `planmgr`
- Context compilation is read-only over plan truth
- Common + specific delta is the preferred authoring transport
- Frozen/normative changes require cascade discipline
