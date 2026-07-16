"""Context/prompt and gate/cascade/misc command-family facade mixin.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

from typing import Any


class ContextGateCommandsMixin:
    """One method per plan_manager command in the context/prompt and gate/cascade/misc family.

    Assumes it is mixed into a class that also inherits
    plan_manager_client.dispatch._CommandDispatchMixin, which supplies the
    coroutine async def _call(self, command: str, params: dict[str, Any] | None = None) -> Any
    used by every method below.
    """

    async def branch_prompt(self, **params: Any) -> Any:
        """Assemble the deterministic executor prompt for one branch and report its token estimate against the plan's context budget."""
        return await self._call("branch_prompt", params)

    async def plan_prompt_chain(self, **params: Any) -> Any:
        """Assemble a paginated page of the deterministic, deduplicated prompt-chain artifact for a gate-green plan scope."""
        return await self._call("plan_prompt_chain", params)

    async def context_compile(self, **params: Any) -> Any:
        """Compile a typed context block directly from concept ids."""
        return await self._call("context_compile", params)

    async def context_common(self, **params: Any) -> Any:
        """Compile the shared common context block for a parent node."""
        return await self._call("context_common", params)

    async def context_specific(self, **params: Any) -> Any:
        """Compile a child-specific delta over a common context block."""
        return await self._call("context_specific", params)

    async def context_bundle(self, **params: Any) -> Any:
        """Compile a common context block and child-specific deltas."""
        return await self._call("context_bundle", params)

    async def block_get(self, **params: Any) -> Any:
        """Return one stored context block by UUID."""
        return await self._call("block_get", params)

    async def block_list(self, **params: Any) -> Any:
        """List a paginated page of stored context block records for a plan."""
        return await self._call("block_list", params)

    async def branch_dump(self, **params: Any) -> Any:
        """Write the executor prompt of every branch of the plan under the configured export root as an explicitly non-authoritative derived snapshot."""
        return await self._call("branch_dump", params)

    async def branch_weak(self, **params: Any) -> Any:
        """Rank the plan's branches by ascending semantic index, refusing when the plan has not passed the mechanical gate."""
        return await self._call("branch_weak", params)

    async def plan_validate(self, **params: Any) -> Any:
        """Run the mechanical gate over a plan or one branch and report PASS/FAIL findings."""
        return await self._call("plan_validate", params)

    async def plan_score(self, **params: Any) -> Any:
        """Run the semantic scoring layer over a plan or one branch and return index, trust, and color."""
        return await self._call("plan_score", params)

    async def cascade_begin(self, **params: Any) -> Any:
        """Open a new cascade transaction on a plan, anchored at its current head revision."""
        return await self._call("cascade_begin", params)

    async def cascade_preview(self, **params: Any) -> Any:
        """Report the accumulated change set, needs_review blast radius, and mechanical gate verdict of a plan's open cascade."""
        return await self._call("cascade_preview", params)

    async def cascade_commit(self, **params: Any) -> Any:
        """Publish the plan's open cascade atomically: advance the head revision on a green gate, or refuse on a red gate."""
        return await self._call("cascade_commit", params)

    async def cascade_abort(self, **params: Any) -> Any:
        """Discard the plan's open cascade, restoring the working state to the base revision."""
        return await self._call("cascade_abort", params)

    async def plan_unfreeze(self, **params: Any) -> Any:
        """Reopen a fully frozen plan: audit the escape and open a cascade under which scoped step_transition frozen->draft may then run."""
        return await self._call("plan_unfreeze", params)

    async def srt_snapshot_create(self, **params: Any) -> Any:
        """Create a semantic tree snapshot: the sole write operation of the SRT command surface."""
        return await self._call("srt_snapshot_create", params)

    async def srt_snapshot_list(self, **params: Any) -> Any:
        """List a paginated page of the retained history of semantic tree snapshots for a plan (read-only)."""
        return await self._call("srt_snapshot_list", params)

    async def srt_diff(self, **params: Any) -> Any:
        """Compute the semantic diff between two semantic tree snapshots (read-only)."""
        return await self._call("srt_diff", params)

    async def info(self, **params: Any) -> Any:
        """Return the server self-description: identity, build metadata, runtime summary, capabilities, planning standards, and documentation."""
        return await self._call("info", params)

    async def command_catalog_dump(self, **params: Any) -> Any:
        """Return the complete machine-readable command catalog, generated from the live command inventory."""
        return await self._call("command_catalog_dump", params)


__all__ = ["ContextGateCommandsMixin"]
