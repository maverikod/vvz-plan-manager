"""Remove obsolete plan step directories."""
import shutil
from pathlib import Path

base = Path("/home/vasilyvz/projects/tools/plan_manager/docs/plans/2026-05-07-plan-manager-mcp-api")

old_dirs = [
    "G-001-mcp-api-surface/T-002-buf-session",
    "G-001-mcp-api-surface/T-003-buf-get",
    "G-001-mcp-api-surface/T-004-buf-content",
    "G-001-mcp-api-surface/T-005-buf-tree-ops",
    "G-001-mcp-api-surface/T-006-buf-history",
    "G-001-mcp-api-surface/T-007-buf-flush",
    "G-001-mcp-api-surface/T-008-buf-diff",
    "G-001-mcp-api-surface/T-009-nav-list-tree",
    "G-001-mcp-api-surface/T-010-nav-node",
    "G-001-mcp-api-surface/T-011-structure-create",
    "G-001-mcp-api-surface/T-012-structure-add",
    "G-001-mcp-api-surface/T-013-validate",
    "G-004-vectorization/T-002-flush-hook",
    "G-004-vectorization/T-003-worker",
    "G-005-service-diagnostics/T-001-session-stats",
    "G-005-service-diagnostics/T-002-plan-stats",
    "G-005-service-diagnostics/T-003-git-health",
    "G-005-service-diagnostics/T-004-worker-status",
    "G-005-service-diagnostics/T-005-status-command",
]

for d in old_dirs:
    p = base / d
    if p.exists():
        shutil.rmtree(p)
        print(f"REMOVED: {d}")
    else:
        print(f"SKIP: {d}")

print("Done.")