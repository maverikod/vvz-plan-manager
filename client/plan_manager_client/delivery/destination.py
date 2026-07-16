"""Path A destination resolution: CA project binding and tree paths.

Resolves the target code-analysis project identity under SHARED PROJECT
IDENTITY (DeliveryDestinationAddressing, MRS concept C-006) and maps each
export tree entry to its destination path inside the project's
documentation area, preserving the entry's relative position beneath the
destination subdirectory so the delivered tree reproduces the export
layout (PathACodeAnalysisDelivery, MRS concept C-003).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


class NoBoundProjectError(Exception):
    """Raised when a Path A delivery is attempted with no bound CA project.

    Raised by :func:`resolve_destination` when both ``plan_project_binding``
    and ``project_id_override`` are ``None``: SHARED PROJECT IDENTITY (C-006)
    requires the plan to carry a bound primary code-analysis project_id, or
    an explicit override, before a Path A call may proceed.
    """
    pass


class DestinationPathTraversalError(Exception):
    """Raised when a resolved destination path escapes the project root.

    Raised by :func:`resolve_destination` when the destination subdirectory
    or a per-entry destination path is absolute or contains a '..' path
    segment, per the traversal-refusal rule of DeliveryDestinationAddressing
    (MRS concept C-006).
    """
    pass


DEFAULT_DESTINATION_SUBDIRECTORY_TEMPLATE: str = "docs/plan-exports/{plan_name}/"
# Default destination subdirectory template (MRS concept C-006); it roots the delivered tree and is formatted with plan_name when the caller supplies no override.


@dataclass(frozen=True)
class ResolvedDestination:
    """Resolved CA project and per-entry destination paths for Path A.

    Attributes:
        resolved_project_id: The code-analysis project_id the delivery
            will write into.
        resolved_destination_subdirectory: The destination documentation
            subdirectory rooting the delivered tree, project-relative
            POSIX, always ending in a single trailing '/'.
        resolved_destination_paths: Ordered per-entry project-relative
            POSIX destination paths, one per entry of tree_relative_paths
            in the same order, each preserving that entry's relative
            position beneath the subdirectory.
    """
    resolved_project_id: str
    resolved_destination_subdirectory: str
    resolved_destination_paths: list[str] = field(default_factory=list)


def _reject_traversal(path: str) -> None:
    """Raise DestinationPathTraversalError for an unsafe POSIX path.

    Args:
        path: A POSIX path string to validate.

    Raises:
        DestinationPathTraversalError: If path starts with '/' or any
            '/'-separated segment of path equals '..'.
    """
    if path.startswith('/') or '..' in path.split('/'):
        raise DestinationPathTraversalError(f"destination path escapes the project root: {path!r}")


def resolve_destination(
        plan_name: str,
        tree_relative_paths: list[str],
        plan_project_binding: Optional[str],
        project_id_override: Optional[str] = None,
        destination_subdirectory_override: Optional[str] = None,
    ) -> ResolvedDestination:
    """Resolve the CA project and per-entry destination paths for Path A.

    Args:
        plan_name: Name of the plan being delivered; used to format the
            default destination subdirectory when no override is supplied.
        tree_relative_paths: The export tree entries' POSIX paths relative
            to the plan export root, in tree order. These are nested paths
            such as 'spec.yaml' or
            'G-001-x/T-001-y/atomic_steps/A-001-z.yaml'; their relative
            position is preserved into the destination.
        plan_project_binding: The plan's bound primary code-analysis
            project_id, or None when the plan has no bound project.
        project_id_override: An explicit code-analysis project_id supplied
            by the caller; takes precedence over plan_project_binding when
            not None.
        destination_subdirectory_override: An explicit destination
            documentation subdirectory rooting the delivered tree; when
            None, the default template formatted with plan_name is used.

    Returns:
        A ResolvedDestination carrying the resolved project_id, the
        resolved destination subdirectory (normalized to end with a single
        trailing '/'), and the per-entry destination paths in the same
        order as tree_relative_paths.

    Raises:
        NoBoundProjectError: If both plan_project_binding and
            project_id_override are None.
        DestinationPathTraversalError: If the resolved destination
            subdirectory is unsafe per _reject_traversal, or if any entry
            of tree_relative_paths is itself unsafe per _reject_traversal,
            or if any resolved destination path is unsafe per
            _reject_traversal.
    """
    resolved_project_id = project_id_override if project_id_override is not None else plan_project_binding

    if resolved_project_id is None:
        raise NoBoundProjectError("Path A delivery requires a bound or overridden CA project_id")

    subdirectory = destination_subdirectory_override if destination_subdirectory_override else DEFAULT_DESTINATION_SUBDIRECTORY_TEMPLATE.format(plan_name=plan_name)

    if not subdirectory.endswith('/'):
        subdirectory = subdirectory + '/'

    _reject_traversal(subdirectory)

    destination_paths = []
    for relative_path in tree_relative_paths:
        _reject_traversal(relative_path)
        candidate = subdirectory + relative_path
        _reject_traversal(candidate)
        destination_paths.append(candidate)

    return ResolvedDestination(
        resolved_project_id=resolved_project_id,
        resolved_destination_subdirectory=subdirectory,
        resolved_destination_paths=destination_paths
    )
