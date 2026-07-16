"""Step-core and graph/dependency command-family facade mixin.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class StepGraphCommandsMixin:
    """One method per plan_manager command in the step-core and graph/dependency family.

    Assumes it is mixed into a class that also inherits
    plan_manager_client.dispatch._CommandDispatchMixin, which supplies the
    coroutine async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def step_get(self, **params: Any) -> Any:
        """Return one step of a plan identified by step_id, with resolved parent context."""
        return await self._call("step_get", params)

    async def step_tree(self, **params: Any) -> Any:
        """Return a paginated page of the plan's full step tree as a flat, sorted list with statuses."""
        return await self._call("step_tree", params)

    async def step_create(self, **params: Any) -> Any:
        """Scaffold a new step under a plan's declarative level schema."""
        return await self._call("step_create", params)

    async def step_update(self, **params: Any) -> Any:
        """Patch level-specific fields of an existing step, re-validating touched references."""
        return await self._call("step_update", params)

    async def step_move(self, **params: Any) -> Any:
        """Move a step to a new parent, rewriting every reference to it in one operation."""
        return await self._call("step_move", params)

    async def step_delete(self, **params: Any) -> Any:
        """Delete a step, with a dry-run impact preview enabled by default."""
        return await self._call("step_delete", params)

    async def step_set_status(self, **params: Any) -> Any:
        """Transition a step's status, refusing illegal and cascade-reserved transitions."""
        return await self._call("step_set_status", params)

    async def step_transition(self, **params: Any) -> Any:
        """Transition one step or a scope of steps through the authoring lifecycle."""
        return await self._call("step_transition", params)

    async def step_runtime_get(self, **params: Any) -> Any:
        """Return runtime parameters for one plan step."""
        return await self._call("step_runtime_get", params)

    async def step_runtime_report(self, **params: Any) -> Any:
        """Merge runtime parameters for one plan step."""
        return await self._call("step_runtime_report", params)

    async def step_runtime_list(self, **params: Any) -> Any:
        """List a paginated, artifact_path-sorted page of runtime parameters for plan steps in a scope."""
        return await self._call("step_runtime_list", params)

    async def step_list(self, **params: Any) -> Any:
        """Return a flat, paginated listing of a plan's steps with full step fields, filterable by level, parent, status, and target_file."""
        return await self._call("step_list", params)

    async def step_search(self, **params: Any) -> Any:
        """Search step content for an exact substring or regex, scoped to a plan or one branch."""
        return await self._call("step_search", params)

    async def files_report(self, **params: Any) -> Any:
        """Return the target_file to writer-steps matrix for a plan scope, with ordering-conflict detection."""
        return await self._call("files_report", params)

    async def step_xref(self, **params: Any) -> Any:
        """Cross-reference report over per-field content fingerprints: report where a signature/text fragment or a given step field is DEFINED versus where it is INLINED across the plan."""
        return await self._call("step_xref", params)

    async def graph_deps(self, **params: Any) -> Any:
        """Return the dependency neighborhood (depends_on and dependents) of one step."""
        return await self._call("graph_deps", params)

    async def graph_order(self, **params: Any) -> Any:
        """Return a paginated page of the topological execution order of a plan's steps."""
        return await self._call("graph_order", params)

    async def graph_parallel_map(self, **params: Any) -> Any:
        """Return a paginated page of the parallel wave partition of a plan's steps by prerequisite depth."""
        return await self._call("graph_parallel_map", params)

    async def graph_impact(self, **params: Any) -> Any:
        """Return the read-only transitive impact set of one step."""
        return await self._call("graph_impact", params)

    async def graph_dependents(self, **params: Any) -> Any:
        """Return a paginated page of the transitive dependency-edge closure of one step."""
        return await self._call("graph_dependents", params)

    async def step_dependency_list(self, **params: Any) -> Any:
        """List one step's top-level depends_on edges and the sibling steps that depend on it."""
        return await self._call("step_dependency_list", params)

    async def step_dependency_add(self, **params: Any) -> Any:
        """Add one sibling dependency to a step's top-level depends_on; idempotent, cycle-safe, and admitted under the step mutation regime."""
        return await self._call("step_dependency_add", params)

    async def step_dependency_remove(self, **params: Any) -> Any:
        """Remove one dependency from a step's top-level depends_on; idempotent and admitted under the step mutation regime."""
        return await self._call("step_dependency_remove", params)

    async def step_dependency_set(self, **params: Any) -> Any:
        """Replace a step's entire top-level depends_on with a validated, deduplicated, cycle-safe sibling list."""
        return await self._call("step_dependency_set", params)

    async def step_dependency_clear(self, **params: Any) -> Any:
        """Clear all of a step's top-level depends_on edges, admitted under the step mutation regime."""
        return await self._call("step_dependency_clear", params)

    async def step_dependency_preview(self, **params: Any) -> Any:
        """Dry-run a batch of dependency changes and report validity, cycle risk, and the before/after execution order and parallel waves."""
        return await self._call("step_dependency_preview", params)

    async def step_dependency_apply(self, **params: Any) -> Any:
        """Apply a batch of dependency changes as one revision, or dry-run them; all-or-nothing, cycle-safe."""
        return await self._call("step_dependency_apply", params)


__all__ = ["StepGraphCommandsMixin"]
