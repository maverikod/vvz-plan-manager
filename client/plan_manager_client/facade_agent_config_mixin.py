"""Agent-configuration data-layer command-family facade mixin (CR-5a: tool/toolset/role/provider/model/invocation-profile entities and their resolve commands).

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class AgentConfigCommandsMixin:
    """One method per plan_manager command in the CR-5a agent-configuration data-layer family.

    Covers the six entity families introduced by CR-5a -- tool (C-001), toolset
    (C-002) plus its ordered membership, role (C-003), provider (C-004), model
    (C-005), and invocation profile (C-008) -- together with the three resolve
    commands that read the level-indirected configuration for a concrete
    plan/step/role target: role_model_resolve (C-006), step_assignment_resolve
    (C-007), and invocation_profile_resolve (C-008). Assumes it is mixed into a
    class that also inherits plan_manager_client.dispatch._CommandDispatchMixin,
    which supplies the coroutine
    async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def tool_create(self, **params: Any) -> Any:
        """Create a new tool instrument record (C-001): a server reference, a command name, and a pinned option set."""
        return await self._call("tool_create", params)

    async def tool_get(self, **params: Any) -> Any:
        """Retrieve a single tool instrument record (C-001) by its tool identifier."""
        return await self._call("tool_get", params)

    async def tool_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing tool instrument record (C-001) in place."""
        return await self._call("tool_update", params)

    async def tool_list(self, **params: Any) -> Any:
        """List a paginated page of tool instrument records (C-001) filtered by name."""
        return await self._call("tool_list", params)

    async def tool_delete(self, **params: Any) -> Any:
        """Delete a tool instrument record (C-001): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("tool_delete", params)

    async def toolset_create(self, **params: Any) -> Any:
        """Create a new toolset record (C-002): a named, ordered set of tool references describing the equipment list of one kind of work."""
        return await self._call("toolset_create", params)

    async def toolset_get(self, **params: Any) -> Any:
        """Retrieve a single toolset record (C-002) by its toolset identifier."""
        return await self._call("toolset_get", params)

    async def toolset_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing toolset record (C-002) in place."""
        return await self._call("toolset_update", params)

    async def toolset_list(self, **params: Any) -> Any:
        """List a paginated page of toolset records (C-002) filtered by name."""
        return await self._call("toolset_list", params)

    async def toolset_delete(self, **params: Any) -> Any:
        """Delete a toolset record (C-002): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("toolset_delete", params)

    async def toolset_member_add(self, **params: Any) -> Any:
        """Add an ordered tool reference to a toolset (C-002 uses C-001): attaches one tool_uuid at a given position without embedding the Tool record."""
        return await self._call("toolset_member_add", params)

    async def toolset_member_remove(self, **params: Any) -> Any:
        """Remove (soft-delete) one ordered tool-reference membership from a toolset (C-002 uses C-001)."""
        return await self._call("toolset_member_remove", params)

    async def role_create(self, **params: Any) -> Any:
        """Create a new role record (C-003): a first-class stored entity naming who the agent is."""
        return await self._call("role_create", params)

    async def role_get(self, **params: Any) -> Any:
        """Retrieve a single role record (C-003) by its role identifier."""
        return await self._call("role_get", params)

    async def role_update(self, **params: Any) -> Any:
        """Patch the mutable description field of an existing role record (C-003) in place."""
        return await self._call("role_update", params)

    async def role_list(self, **params: Any) -> Any:
        """List a paginated page of role records (C-003)."""
        return await self._call("role_list", params)

    async def role_delete(self, **params: Any) -> Any:
        """Delete a role record (C-003): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("role_delete", params)

    async def provider_create(self, **params: Any) -> Any:
        """Create a new provider record (C-004): the source that serves a model, carrying its type, hardware ownership, activity status, and billing notes."""
        return await self._call("provider_create", params)

    async def provider_get(self, **params: Any) -> Any:
        """Retrieve a single provider record (C-004) by its provider identifier."""
        return await self._call("provider_get", params)

    async def provider_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing provider record (C-004) in place."""
        return await self._call("provider_update", params)

    async def provider_list(self, **params: Any) -> Any:
        """List a paginated page of provider records (C-004) filtered by type and status."""
        return await self._call("provider_list", params)

    async def provider_delete(self, **params: Any) -> Any:
        """Delete a provider record (C-004): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("provider_delete", params)

    async def provider_set_status(self, **params: Any) -> Any:
        """Switch a provider's activity status in a single call (C-004): the dedicated switching-axis operation, distinct from the general provider_update."""
        return await self._call("provider_set_status", params)

    async def model_create(self, **params: Any) -> Any:
        """Create a new invocable model record (C-005): name, provider reference, capability level, and execution mode."""
        return await self._call("model_create", params)

    async def model_get(self, **params: Any) -> Any:
        """Retrieve a single invocable model record (C-005) by its model identifier."""
        return await self._call("model_get", params)

    async def model_update(self, **params: Any) -> Any:
        """Patch the mutable fields of an existing invocable model record (C-005) in place."""
        return await self._call("model_update", params)

    async def model_list(self, **params: Any) -> Any:
        """List a paginated page of invocable model records (C-005) filtered by provider, level, and execution mode."""
        return await self._call("model_list", params)

    async def model_delete(self, **params: Any) -> Any:
        """Delete an invocable model record (C-005): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("model_delete", params)

    async def invocation_profile_create(self, **params: Any) -> Any:
        """Create an invocation profile runtime-configuration record (C-008) for the given scope."""
        return await self._call("invocation_profile_create", params)

    async def invocation_profile_get(self, **params: Any) -> Any:
        """Retrieve a single invocation profile record (C-008) by its profile identifier."""
        return await self._call("invocation_profile_get", params)

    async def invocation_profile_update(self, **params: Any) -> Any:
        """Patch the mutable informational fields of an existing invocation profile record (C-008) in place."""
        return await self._call("invocation_profile_update", params)

    async def invocation_profile_list(self, **params: Any) -> Any:
        """List a paginated page of invocation profile records (C-008) filtered by plan, scope, and role."""
        return await self._call("invocation_profile_list", params)

    async def invocation_profile_delete(self, **params: Any) -> Any:
        """Delete an invocation profile record (C-008): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."""
        return await self._call("invocation_profile_delete", params)

    async def role_model_resolve(self, **params: Any) -> Any:
        """Resolve the effective (provider, model) for a role from active providers, explicit model bindings, and the manual role-model level relation (C-006)."""
        return await self._call("role_model_resolve", params)

    async def step_assignment_resolve(self, **params: Any) -> Any:
        """Resolve the effective per-step role and toolset assignment along the six-scope specificity ladder (C-007)."""
        return await self._call("step_assignment_resolve", params)

    async def invocation_profile_resolve(self, **params: Any) -> Any:
        """Resolve the effective invocation profile along the six-scope specificity ladder (C-008)."""
        return await self._call("invocation_profile_resolve", params)


__all__ = ["AgentConfigCommandsMixin"]
