<!--
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
-->

# Maintainers only (not linked from subagent prompts)

**Do not** `@`-include this file in agent tasks. It is for humans maintaining a **template** fork.

## Forking this repository

1. Sync or replace [`PROJECT_RULES.md`](../PROJECT_RULES.md) with your organization’s master copy.
2. Replace [`project_overlay.md`](project_overlay.md) for the new product.
3. Edit [`PROJECT_RULES.md`](../PROJECT_RULES.md) §0; remove or replace §7.
4. Trim `.cursor/agents/*.md` bodies if workflows differ; keep the **Agent context stack** links at the top of each card.
