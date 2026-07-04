"""BranchPromptCommand: assemble the deterministic executor prompt for one branch."""
from typing import Any, ClassVar, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.branch_prompt_metadata import get_branch_prompt_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.views.branch import resolve_branch
from plan_manager.views.prompt_assembly import assemble_prompt, token_estimate


class BranchPromptCommand(Command):
    """Assemble and return the executor prompt for one branch, read-only."""

    name: ClassVar[str] = "branch_prompt"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Assemble the deterministic executor prompt for one branch and "
        "report its token estimate against the plan's context budget."
    )
    category: ClassVar[str] = "branch"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for this command.

        :return: A dict with object type, properties for plan,
            gs_step_id, ts_step_id, as_step_id (all type string with
            descriptions), a required list naming all four, and
            additionalProperties False.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID).",
                },
                "gs_step_id": {
                    "type": "string",
                    "description": "Global step id of the branch, e.g. 'G-005'.",
                },
                "ts_step_id": {
                    "type": "string",
                    "description": "Tactical step id of the branch, e.g. 'T-008'.",
                },
                "as_step_id": {
                    "type": "string",
                    "description": "Atomic step id of the branch, e.g. 'A-001'.",
                },
            },
            "required": ["plan", "gs_step_id", "ts_step_id", "as_step_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return extended AI/documentation metadata for this command.

        :return: The dictionary produced by get_branch_prompt_metadata(cls).
        """
        return get_branch_prompt_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the raw parameters for this command.

        :param params: Raw parameter dict as received from the
            adapter, already checked against get_schema(): object
            type, the four required keys plan, gs_step_id, ts_step_id,
            as_step_id present, all four values of type string, no
            additional properties.
        :return: The params dict, unchanged beyond the base validation
            already performed by the superclass. No further semantic
            validation applies to this command: existence of the plan
            and of each step id is resolved and reported as a domain
            error during execute(), not during schema validation.
        """
        params = super().validate_params(params)
        return params

    def execute(
        self,
        plan: str,
        gs_step_id: str,
        ts_step_id: str,
        as_step_id: str,
    ) -> SuccessResult | ErrorResult:
        """Resolve one branch, assemble its prompt, and report the budget verdict.

        :param plan: Plan identifier (name or UUID) resolved via
            resolve_plan(conn, plan) -> Plan (fields uuid, name,
            status, context_budget, head_revision_uuid).
        :param gs_step_id: Global step id of the branch (e.g. 'G-005').
        :param ts_step_id: Tactical step id of the branch (e.g. 'T-008').
        :param as_step_id: Atomic step id of the branch (e.g. 'A-001').
        :return: SuccessResult(data={"prompt": str, "token_estimate": int,
            "context_budget": int, "within_budget": bool}) on success;
            ErrorResult with code STEP_NOT_FOUND when resolve_branch
            raises ValueError naming the missing step id; ErrorResult
            from map_exception(exc) for any other exception, including
            a DomainCommandError with code PLAN_NOT_FOUND raised by
            resolve_plan when the plan does not resolve.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                try:
                    branch = resolve_branch(
                        conn, p.uuid, gs_step_id, ts_step_id, as_step_id
                    )
                except ValueError as exc:
                    return domain_error("STEP_NOT_FOUND", str(exc))
                text = assemble_prompt(conn, branch)
                est = token_estimate(text)
                return SuccessResult(
                    data={
                        "prompt": text,
                        "token_estimate": est,
                        "context_budget": p.context_budget,
                        "within_budget": est <= p.context_budget,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
