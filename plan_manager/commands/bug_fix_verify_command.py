"""Command: record a verification outcome for a fix attempt (C-024)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_derived_status_store import recompute_bug_status
from plan_manager.storage.bug_fix_store import get_bug_fix, verify_bug_fix


class BugFixVerifyCommand(Command):
    name: ClassVar[str] = "bug_fix_verify"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Record a verification outcome for a fix attempt (C-024)."
    category: ClassVar[str] = "fix"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **BASE_PARAMETERS,
                "bug_fix": {"type": "string", "format": "uuid", "description": "UUID of the BugFix (C-024) fix attempt being verified."},
                "changed_by": {"type": "string", "description": "Identifier of the actor performing this verification, recorded for audit purposes."},
                "passed": {"type": "boolean", "description": "Whether the verification passed; sets the fix attempt status to verified when true, failed when false."},
                "verification_method": {"type": "string", "description": "The verification method used (e.g. manual test, automated test run)."},
                "actual_result": {"type": "string", "description": "The actual result observed during verification."},
            },
            "required": ["plan", "bug_fix", "changed_by", "passed"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return bug_fix_metadata(
            cls,
            params,
            {"success": {"description": "The verified BugFix (C-024) payload, with status set to verified or failed."}},
            [{"description": "Record a passing verification for a fix attempt.", "command": {"plan": "plan_manager", "bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent", "passed": True, "actual_result": "Reproduction steps no longer trigger the defect."}}],
        )

    async def execute(
        self,
        plan: str,
        bug_fix: str,
        changed_by: str,
        passed: bool,
        verification_method: str | None = None,
        actual_result: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                fix_uuid = uuid.UUID(bug_fix)
                existing = get_bug_fix(conn, fix_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_FIX_NOT_FOUND", f"bug fix not found: {bug_fix}")
                record = verify_bug_fix(
                    conn,
                    fix_uuid,
                    changed_by=changed_by,
                    passed=passed,
                    verification_method=verification_method,
                    actual_result=actual_result,
                )
                recompute_bug_status(conn, existing.bug_uuid, changed_by=changed_by)
                return SuccessResult(data={"bug_fix": record.to_payload()})
        except Exception as exc:
            return map_exception(exc)
