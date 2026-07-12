"""Server self-description command (C-025)."""

from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.info_metadata import get_info_metadata
from plan_manager.commands.info_reference import (
    bug_lifecycle_capabilities,
    context_block_capabilities,
    execution_attempt_capabilities,
    model_binding_capabilities,
    overlay_capabilities,
    plan_lifecycle_capabilities,
    planning_standards_reference,
    project_binding_capabilities,
    project_dependency_capabilities,
    prompt_chain_capabilities,
    review_escalation_capabilities,
    runtime_comment_capabilities,
    runtime_filtering_capabilities,
    runtime_write_invariants,
    step_dependency_capabilities,
    step_lifecycle_capabilities,
    todo_work_capabilities,
)
from plan_manager.commands.info_reference_delegation import (
    delegated_authoring_method_reference,
)
from plan_manager.commands.info_reference_mechanism import (
    semantic_reproduction_mechanism_reference,
)
from plan_manager.runtime.build_info import build_info, operator_doc
from plan_manager.runtime.context import db_connection
from plan_manager.runtime.probes import probe_database, probe_embedding


_SECTIONS = (
    "identity",
    "build",
    "runtime",
    "capabilities",
    "planning_standards",
    "documentation",
    "mechanism_documentation",
    "delegation_method_documentation",
)


class InfoCommand(Command):
    """Return server identity, runtime state, docs, and agent reference data."""

    name = "info"
    version = "1.0.0"
    descr = (
        "Return the server self-description: identity, build metadata, "
        "runtime summary, capabilities, planning standards, and documentation."
    )
    category = "system"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Restrict the response to one section: identity, build, "
                        "runtime, capabilities, planning_standards, documentation, "
                        "mechanism_documentation, or delegation_method_documentation. "
                        "Omitting this parameter returns all sections."
                    ),
                    "enum": list(_SECTIONS),
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = super().validate_params(params)
        section = params.get("section")
        if section is not None and section not in _SECTIONS:
            raise ValueError(
                f"Invalid section: {section!r}. Must be one of {', '.join(_SECTIONS)}."
            )
        return params

    async def execute(
        self,
        section: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            info = build_info()
            if section is not None:
                data: Dict[str, Any] = {
                    "section": section,
                    section: self._section_data(section, info),
                }
            else:
                data = {
                    name: self._section_data(name, info)
                    for name in _SECTIONS
                }

            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @staticmethod
    def _section_data(section: str, info: dict[str, Any]) -> Any:
        if section == "identity":
            return {
                "product": info["product"],
                "package_version": info["package_version"],
                "adapter_version": info["adapter_version"],
            }
        if section == "build":
            return {
                "build_date": info["build_date"],
                "image_tag": info["image_tag"],
            }
        if section == "runtime":
            return InfoCommand._runtime_summary()
        if section == "capabilities":
            return {
                "project_bindings": project_binding_capabilities(),
                "context_blocks": context_block_capabilities(),
                "prompt_chain": prompt_chain_capabilities(),
                "step_lifecycle": step_lifecycle_capabilities(),
                "step_dependencies": step_dependency_capabilities(),
                "plan_lifecycle": plan_lifecycle_capabilities(),
                "todo_work": todo_work_capabilities(),
                "runtime_comments": runtime_comment_capabilities(),
                "execution_attempts": execution_attempt_capabilities(),
                "review_escalations": review_escalation_capabilities(),
                "model_bindings": model_binding_capabilities(),
                "bug_lifecycle": bug_lifecycle_capabilities(),
                "project_dependencies": project_dependency_capabilities(),
                "runtime_filtering": runtime_filtering_capabilities(),
                "overlay": overlay_capabilities(),
                "runtime_write_invariants": runtime_write_invariants(),
            }
        if section == "planning_standards":
            return planning_standards_reference()
        if section == "documentation":
            return {"text": operator_doc()}
        if section == "mechanism_documentation":
            return semantic_reproduction_mechanism_reference()
        if section == "delegation_method_documentation":
            return delegated_authoring_method_reference()
        raise ValueError(f"Invalid section: {section!r}.")

    @staticmethod
    def _runtime_summary() -> dict[str, Any]:
        database_connected = probe_database()

        open_cascades = 0
        if database_connected:
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM cascade WHERE status = 'open'")
                    row = cur.fetchone()
                    open_cascades = row[0] if row is not None else 0

        return {
            "database_connected": database_connected,
            "open_cascades": open_cascades,
            "embedding_service": probe_embedding(),
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_info_metadata(cls)
