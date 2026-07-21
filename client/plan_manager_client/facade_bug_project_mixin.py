"""Bug and project-dependency command-family facade mixin.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class BugProjectCommandsMixin:
    """One method per plan_manager command in the bug and project-dependency family.

    Assumes it is mixed into a class that also inherits
    plan_manager_client.dispatch._CommandDispatchMixin, which supplies the
    coroutine async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def bug_create(self, **params: Any) -> Any:
        """Create a new bug report with its single primary source anchor."""
        return await self._call("bug_create", params)

    async def bug_get(self, **params: Any) -> Any:
        """Retrieve a single bug report by identifier."""
        return await self._call("bug_get", params)

    async def bug_list(self, **params: Any) -> Any:
        """List bug reports with filtering and pagination."""
        return await self._call("bug_list", params)

    async def bug_update(self, **params: Any) -> Any:
        """Patch mutable fields of an existing bug report."""
        return await self._call("bug_update", params)

    async def bug_reanchor(self, **params: Any) -> Any:
        """Move a bug report's primary source anchor to a new target, with an audit record."""
        return await self._call("bug_reanchor", params)

    async def bug_triage(self, **params: Any) -> Any:
        """Transition a bug report to status triaged."""
        return await self._call("bug_triage", params)

    async def bug_confirm(self, **params: Any) -> Any:
        """Transition a bug report to status confirmed."""
        return await self._call("bug_confirm", params)

    async def bug_reject(self, **params: Any) -> Any:
        """Transition a bug report to status rejected."""
        return await self._call("bug_reject", params)

    async def bug_mark_duplicate(self, **params: Any) -> Any:
        """Mark a bug report as a duplicate of another bug report."""
        return await self._call("bug_mark_duplicate", params)

    async def bug_reopen(self, **params: Any) -> Any:
        """Transition a bug report to status reopened on re-discovery."""
        return await self._call("bug_reopen", params)

    async def bug_close(self, **params: Any) -> Any:
        """Transition a bug report to status closed after enforcing the closure discipline invariant on server-derived state."""
        return await self._call("bug_close", params)

    async def bug_impact_add(self, **params: Any) -> Any:
        """Create one BugImpact record describing an object affected by a bug."""
        return await self._call("bug_impact_add", params)

    async def bug_impact_update(self, **params: Any) -> Any:
        """Transition the status or amend fields of an existing BugImpact record."""
        return await self._call("bug_impact_update", params)

    async def bug_impact_list(self, **params: Any) -> Any:
        """List BugImpact records for a bug, with uniform filtering and pagination."""
        return await self._call("bug_impact_list", params)

    async def bug_impact_discover(self, **params: Any) -> Any:
        """Auto-discover the suspected impact set of a bug from the reverse project dependency graph."""
        return await self._call("bug_impact_discover", params)

    async def bug_fix_create(self, **params: Any) -> Any:
        """Create a new fix attempt for a bug (C-024)."""
        return await self._call("bug_fix_create", params)

    async def bug_fix_update(self, **params: Any) -> Any:
        """Update fields or advance the status of an existing bug fix attempt (C-024)."""
        return await self._call("bug_fix_update", params)

    async def bug_fix_list(self, **params: Any) -> Any:
        """List the fix attempts recorded for a bug, filtered and paginated (read-only)."""
        return await self._call("bug_fix_list", params)

    async def bug_fix_verify(self, **params: Any) -> Any:
        """Record a verification outcome for a fix attempt (C-024)."""
        return await self._call("bug_fix_verify", params)

    async def bug_propagation_create(self, **params: Any) -> Any:
        """Create a bug fix propagation record for one impact target after a source fix."""
        return await self._call("bug_propagation_create", params)

    async def bug_propagation_list(self, **params: Any) -> Any:
        """List a paginated page of bug fix propagation records filtered by bug fix or impact (read-only)."""
        return await self._call("bug_propagation_list", params)

    async def bug_propagation_update(self, **params: Any) -> Any:
        """Update a bug fix propagation record's status, assignment, evidence, or linked TODO."""
        return await self._call("bug_propagation_update", params)

    async def bug_propagation_generate_todos(self, **params: Any) -> Any:
        """Generate linked TODO items for every pending propagation of a bug fix."""
        return await self._call("bug_propagation_generate_todos", params)

    async def project_dependency_add(self, **params: Any) -> Any:
        """Create a project dependency edge between two external projects."""
        return await self._call("project_dependency_add", params)

    async def project_dependency_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing project dependency edge."""
        return await self._call("project_dependency_update", params)

    async def project_dependency_confirm(self, **params: Any) -> Any:
        """Move a discovered project dependency edge's confidence off suspected to confirmed."""
        return await self._call("project_dependency_confirm", params)

    async def project_dependency_remove(self, **params: Any) -> Any:
        """Soft-delete an existing project dependency edge."""
        return await self._call("project_dependency_remove", params)

    async def project_dependency_list(self, **params: Any) -> Any:
        """List a paginated page of project dependency edges filtered by dependent/depends-on project and active status."""
        return await self._call("project_dependency_list", params)

    async def project_dependency_discover(self, **params: Any) -> Any:
        """Discover the transitive reverse-dependent project set (suspected impact set) for a source project."""
        return await self._call("project_dependency_discover", params)

    async def project_dependents(self, **params: Any) -> Any:
        """List the projects that directly depend on a given project (reverse-dependency lookup)."""
        return await self._call("project_dependents", params)

    async def project_view(self, **params: Any) -> Any:
        """Project-centric aggregate view: paginated todos/bugs (plus a comments count) scoped to one project, direct or transitive via bound plans."""
        return await self._call("project_view", params)


__all__ = ["BugProjectCommandsMixin"]
