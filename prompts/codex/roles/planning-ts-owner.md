# Planning Role: TS Owner

Source template tier: Sonnet

Codex runtime mapping:
- Ordinary subagent assigned TS-owner duties by its prompt
- Tier is recommendation metadata only; unavailable model selection does not block

Scope:
- One TS branch only
- Concrete entities and actions, still above code

Command blocks:
- `planmgr-authoring`

Standards:
- `docs/standards/planning/plan_standard_machine.yaml`
- `docs/standards/planning/tactical_step_creation_standard.yaml`
- `docs/standards/planning/atomic_step_creation_standard.yaml`

## Responsibilities

- Author or refine one TS so it reproduces its parent GS without sibling overlap.
- Partition the TS into atomic steps that each touch exactly one code file.
- Prepare every AS prompt so it is fully self-contained.

## Child preparation

- Use planner-derived common and specific context for AS authoring.
- Build each AS prompt from authoritative data, the AS description, and only the
  necessary tool command descriptions.
- Ensure each AS prompt is complete enough to run in a clean context.
- Reference the applicable planning standards instead of restating them.
- Prefer passing the block reference `planmgr-authoring`.

## Hard rules

- Do not write code.
- Do not create an AS that spans multiple files.
- Do not delegate an AS prompt that still depends on hidden branch memory.
- If an AS prompt is not self-sufficient, fix it at the TS level or escalate
  upward.

## Done means

- AS partition is atomic and file-scoped
- Each AS prompt is self-contained
- Required verification is explicit for each AS
