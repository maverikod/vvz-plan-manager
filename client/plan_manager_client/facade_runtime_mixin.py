"""Todo/runtime-link/comment and model-binding/execution/review/escalation command-family facade mixin.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class RuntimeCommandsMixin:
    """One method per plan_manager command in the runtime work-item family.

    Assumes it is mixed into a class that also inherits
    plan_manager_client.dispatch._CommandDispatchMixin, which supplies the
    coroutine async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def todo_create(self, **params: Any) -> Any:
        """Create a new TODO work item with a primary anchor."""
        return await self._call("todo_create", params)

    async def todo_get(self, **params: Any) -> Any:
        """Fetch a single TODO work item by identifier."""
        return await self._call("todo_get", params)

    async def todo_list(self, **params: Any) -> Any:
        """List TODO work items with uniform filtering and pagination."""
        return await self._call("todo_list", params)

    async def todo_update(self, **params: Any) -> Any:
        """Update mutable fields of an existing TODO work item."""
        return await self._call("todo_update", params)

    async def todo_reanchor(self, **params: Any) -> Any:
        """Move a TODO item's primary anchor to a new target, with an audit record."""
        return await self._call("todo_reanchor", params)

    async def todo_resolve(self, **params: Any) -> Any:
        """Mark a TODO work item resolved."""
        return await self._call("todo_resolve", params)

    async def todo_close(self, **params: Any) -> Any:
        """Mark a TODO work item closed."""
        return await self._call("todo_close", params)

    async def todo_delete(self, **params: Any) -> Any:
        """Delete a TODO work item: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("todo_delete", params)

    async def todo_link_add(self, **params: Any) -> Any:
        """Create a typed link between two TODO work items."""
        return await self._call("todo_link_add", params)

    async def todo_link_remove(self, **params: Any) -> Any:
        """Remove (soft-delete) a typed link between two TODO work items."""
        return await self._call("todo_link_remove", params)

    async def todo_queue(self, **params: Any) -> Any:
        """Surface a paginated page of the TODO-derived portion of the unified runtime work queue."""
        return await self._call("todo_queue", params)

    async def todo_promote_to_cascade_request(self, **params: Any) -> Any:
        """Promote an existing TODO item into a cascade request for a normative plan change."""
        return await self._call("todo_promote_to_cascade_request", params)

    async def runtime_link_add(self, **params: Any) -> Any:
        """Create a typed link between two runtime records, each independently a bug or a todo."""
        return await self._call("runtime_link_add", params)

    async def runtime_link_list(self, **params: Any) -> Any:
        """List generic runtime links, optionally filtered to one endpoint record, with uniform pagination."""
        return await self._call("runtime_link_list", params)

    async def runtime_link_remove(self, **params: Any) -> Any:
        """Remove (soft-delete) a generic runtime link, with an optional dry-run preview."""
        return await self._call("runtime_link_remove", params)

    async def comment_add(self, **params: Any) -> Any:
        """Create a new runtime comment attached to a comment anchor."""
        return await self._call("comment_add", params)

    async def comment_get(self, **params: Any) -> Any:
        """Retrieve a single runtime comment by identifier."""
        return await self._call("comment_get", params)

    async def comment_list(self, **params: Any) -> Any:
        """List runtime comments with uniform filtering and pagination."""
        return await self._call("comment_list", params)

    async def comment_supersede(self, **params: Any) -> Any:
        """Create a new runtime comment that supersedes an existing one, preserving history."""
        return await self._call("comment_supersede", params)

    async def comment_resolve(self, **params: Any) -> Any:
        """Mark an existing runtime comment as resolved."""
        return await self._call("comment_resolve", params)

    async def comment_delete(self, **params: Any) -> Any:
        """Delete a runtime comment: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("comment_delete", params)

    async def model_binding_set(self, **params: Any) -> Any:
        """Create a model binding runtime-configuration record (C-009) for the given scope."""
        return await self._call("model_binding_set", params)

    async def model_binding_get(self, **params: Any) -> Any:
        """Retrieve a single model binding record (C-009) by its binding identifier."""
        return await self._call("model_binding_get", params)

    async def model_binding_list(self, **params: Any) -> Any:
        """List a paginated page of model binding records (C-009) filtered by plan, scope, and role."""
        return await self._call("model_binding_list", params)

    async def model_binding_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing model binding record (C-009) in place."""
        return await self._call("model_binding_update", params)

    async def model_binding_remove(self, **params: Any) -> Any:
        """Soft-delete a model binding record (C-009) by its binding identifier."""
        return await self._call("model_binding_remove", params)

    async def model_binding_resolve(self, **params: Any) -> Any:
        """Resolve the effective model for a target step and role from the binding inheritance (C-012)."""
        return await self._call("model_binding_resolve", params)

    async def execution_attempt_create(self, **params: Any) -> Any:
        """Create a new execution attempt anchored to a plan/step."""
        return await self._call("execution_attempt_create", params)

    async def execution_attempt_report(self, **params: Any) -> Any:
        """Record the outcome of an execution attempt run. Never a confirmation of correctness -- acceptance is recorded separately by a review result."""
        return await self._call("execution_attempt_report", params)

    async def execution_attempt_get(self, **params: Any) -> Any:
        """Retrieve a single execution attempt by identifier."""
        return await self._call("execution_attempt_get", params)

    async def execution_attempt_list(self, **params: Any) -> Any:
        """List a paginated page of execution attempts filtered by plan, step, status, and parent attempt lineage."""
        return await self._call("execution_attempt_list", params)

    async def review_result_create(self, **params: Any) -> Any:
        """Create a review result recording the outcome of reviewing an execution attempt or revision."""
        return await self._call("review_result_create", params)

    async def review_result_get(self, **params: Any) -> Any:
        """Retrieve a single review result by identifier."""
        return await self._call("review_result_get", params)

    async def review_result_list(self, **params: Any) -> Any:
        """List a paginated page of review results scoped by reviewed execution attempt and status."""
        return await self._call("review_result_list", params)

    async def escalation_create(self, **params: Any) -> Any:
        """Create an escalation raised to the owner of the next level up."""
        return await self._call("escalation_create", params)

    async def escalation_get(self, **params: Any) -> Any:
        """Retrieve a single escalation by its identifier."""
        return await self._call("escalation_get", params)

    async def escalation_list(self, **params: Any) -> Any:
        """List escalations with optional status/anchor filtering and pagination."""
        return await self._call("escalation_list", params)

    async def escalation_resolve(self, **params: Any) -> Any:
        """Resolve an open escalation, recording the resolution and the resolving owner."""
        return await self._call("escalation_resolve", params)


__all__ = ["RuntimeCommandsMixin"]
