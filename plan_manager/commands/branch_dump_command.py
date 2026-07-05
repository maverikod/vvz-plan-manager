"""BranchDumpCommand: write every branch's prompt as a non-authoritative snapshot."""
import pathlib
from typing import Any, ClassVar, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.branch_dump_metadata import get_branch_dump_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.prompt_assembly import dump_prompts


class BranchDumpCommand(Command):
    """Dump every branch's executor prompt to disk as a derived snapshot."""

    name: ClassVar[str] = "branch_dump"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Write the executor prompt of every branch of the plan under "
        "the configured export root as an explicitly "
        "non-authoritative derived snapshot."
    )
    category: ClassVar[str] = "branch"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for this command.

        :return: A dict with object type, properties for plan (type
            string) and dry_run (type boolean, default False), a
            required list naming only plan, and additionalProperties
            False.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID).",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "When true, count the branches that would be "
                        "dumped without writing any file. The dump is "
                        "always an explicitly non-authoritative "
                        "derived snapshot regardless of this flag."
                    ),
                    "default": False,
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return extended AI/documentation metadata for this command.

        :return: The dictionary produced by get_branch_dump_metadata(cls).
        """
        return get_branch_dump_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the raw parameters for this command.

        :param params: Raw parameter dict as received from the
            adapter, already checked against get_schema(): object
            type, plan required and of type string, dry_run optional
            and of type boolean when present, no additional
            properties.
        :return: The params dict, unchanged beyond the base validation
            already performed by the superclass. No further semantic
            validation applies to this command: plan existence is
            resolved and reported as a domain error during execute(),
            not during schema validation.
        """
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Dump the executor prompt of every branch of the plan to disk.

        :param plan: Plan identifier (name or UUID) resolved via
            resolve_plan(conn, plan) -> Plan (fields uuid, name,
            status, context_budget, head_revision_uuid).
        :param dry_run: When True, count the branches that would be
            dumped without writing any file. Defaults to False.
        :return: SuccessResult(data={"branches": int, "root": str,
            "dry_run": bool, "non_authoritative": True}) on success;
            ErrorResult from map_exception(exc) for any exception,
            including a DomainCommandError with code PLAN_NOT_FOUND
            raised by resolve_plan when the plan does not resolve. The
            written files are an explicitly non-authoritative derived
            snapshot: they are never read back by the server, and a
            dry_run=True call never touches disk, so calling this
            command is always safe.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                dump_dir = str(
                    pathlib.Path(app_config().export_root)
                    / "prompt_dump"
                    / str(p.uuid)
                )
                if dry_run:
                    nodes = load_steps(conn, p.uuid)
                    count = sum(1 for n in nodes.values() if n.level == 5)
                    return SuccessResult(
                        data={
                            "branches": count,
                            "root": dump_dir,
                            "dry_run": True,
                            "non_authoritative": True,
                        }
                    )
                paths = dump_prompts(conn, p.uuid, dump_dir)
                return SuccessResult(
                    data={
                        "branches": len(paths),
                        "root": dump_dir,
                        "dry_run": False,
                        "non_authoritative": True,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
