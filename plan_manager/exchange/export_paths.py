"""The export-root boundary: resolve a named directory inside the export root (C-016).

plan_manager writes every plan's export under <export_root>/<plan.name>/, and
several operations need that directory resolved safely before they read, pack,
or remove anything. This module owns the single canonical resolver so the
boundary rule is stated once and every caller enforces the identical rule.

The rule is defense-in-depth: the name must be one safe path segment, and the
fully resolved candidate (symlinks followed) must be a DIRECT child of the
resolved export root. Resolving before comparing is what makes '..' segments
and symlink escapes fail closed rather than slipping through a string check.
"""

from __future__ import annotations

import os
from pathlib import Path


def resolve_export_subdirectory(export_root: str, name: str) -> Path | None:
    """Resolve `name` to a direct child directory of `export_root`, or None if unsafe.

    Rejects any name that is empty, is '.' or '..', or contains a path
    separator ('/', os.sep, '\\\\', or os.altsep when defined). Resolves both
    export_root and the candidate to their absolute, symlink-free form and
    requires the candidate's resolved parent to be exactly the resolved
    export_root.

    Args:
        export_root: Configured export root directory (as configured, not
            necessarily already resolved or existing).
        name: Candidate child directory name to resolve.

    Returns:
        Path | None: The resolved absolute directory Path when name is safe
            and its resolved path is a direct child of the resolved
            export_root, regardless of whether the directory currently exists
            on disk. None when name is rejected as unsafe or its resolved path
            is not a direct child of the resolved export_root.
    """
    if not name or name in (".", ".."):
        return None
    if "/" in name or os.sep in name or "\\" in name:
        return None
    if os.altsep and os.altsep in name:
        return None
    root = Path(export_root).resolve()
    candidate = (Path(export_root) / name).resolve()
    if candidate.parent != root:
        return None
    return candidate
