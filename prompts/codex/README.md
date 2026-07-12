# plan_manager Codex prompt bundle

This directory contains the complete Codex prompt bundle specialized for the
`plan_manager` server project. The bundle keeps the original planning,
inspection, analysis, editing, refactoring, terminal, verification, and recovery
methodologies. Only the agent-runtime compatibility layer is translated.

Primary surfaces:

- `../../AGENTS.md`: repository orchestration contract
- `ROLE_TRANSLATION.md`: exhaustive source-role to Codex-duty translation
- `CODEX_RUNTIME_COMPATIBILITY.md`: exact collaboration and MCP Proxy adapter
- `CODEX_COMPATIBILITY_DRY_RUN.md`: scenario-based compatibility evidence
- `roles/`: mode-and-level role prompts
- `command-blocks/`: reusable server command groups
- `../tool-routing/`: lazy trigger and live-help routing library
- `../../docs/standards/planning/`: normative planning and server workflows
- `BUNDLE_PARITY.md`: accounting against the source archive

Project access defaults to `server_project`: Plan Manager, Code Analysis Server,
AI Editor Server, and MCP Terminal are reached through MCP Proxy according to the
routing library. Local files remain the prompt-control and standards source until
the user explicitly authorizes a named local action.

The source Fable, Opus, Sonnet, and Haiku tiers are semantic role labels only.
Codex dispatches the root Orchestrator and ordinary subagents by prompt-assigned
duties. Duty labels are not separate role APIs, and the runtime cannot be
assumed to select or reveal a model.
