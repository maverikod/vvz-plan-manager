<!--
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
-->

# Universal project context (reference map)

All universal rules are in **[`docs/PROJECT_RULES.md`](../PROJECT_RULES.md)**:

| Section | Content |
|---------|---------|
| **§0** | Project profile keys (`PROJECT_SLUG`, `PACKAGE_ROOT`, `VENV_DIR`, locales, …). |
| **§1** | Rule precedence. |
| **§2** | `CR-*` core rules (e.g. **CR-005** venv, **CR-015** pip overrides, **CR-016** parallelize independent work). |
| **§3** | `LAYOUT-*` repository layout. |
| **§4–§5** | `NAME-*` naming and anti-patterns. |

Cross-project layout or naming changes belong **only** in `PROJECT_RULES.md`, not in [`project_overlay.md`](project_overlay.md).

Next file for this repo: [`project_overlay.md`](project_overlay.md).
