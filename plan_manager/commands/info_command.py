"""Server self-description command (C-025)."""

from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.info_metadata import get_info_metadata
from plan_manager.commands.info_reference import (
    context_block_capabilities,
    planning_standards_reference,
    prompt_chain_capabilities,
    project_binding_capabilities,
    step_lifecycle_capabilities,
)
from plan_manager.runtime.build_info import build_info, operator_doc
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.embedding import EmbeddingUnavailable, fetch_vector


_SECTIONS = (
    "identity",
    "build",
    "runtime",
    "capabilities",
    "planning_standards",
    "documentation",
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
                        "runtime, capabilities, planning_standards, or documentation. "
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
            identity = {
                "product": info["product"],
                "package_version": info["package_version"],
                "adapter_version": info["adapter_version"],
            }
            build = {
                "build_date": info["build_date"],
                "image_tag": info["image_tag"],
            }
            runtime = self._runtime_summary()
            capabilities = {
                "project_bindings": project_binding_capabilities(),
                "context_blocks": context_block_capabilities(),
                "prompt_chain": prompt_chain_capabilities(),
                "step_lifecycle": step_lifecycle_capabilities(),
            }
            planning_standards = planning_standards_reference()
            documentation = {"text": operator_doc()}

            parts: Dict[str, Any] = {
                "identity": identity,
                "build": build,
                "runtime": runtime,
                "capabilities": capabilities,
                "planning_standards": planning_standards,
                "documentation": documentation,
            }

            if section is not None:
                data: Dict[str, Any] = {"section": section, section: parts[section]}
            else:
                data = parts

            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @staticmethod
    def _runtime_summary() -> dict[str, Any]:
        database_connected = True
        try:
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
        except Exception:
            database_connected = False

        open_cascades = 0
        if database_connected:
            with db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT count(*) FROM cascade WHERE status = 'open'")
                    row = cur.fetchone()
                    open_cascades = row[0] if row is not None else 0

        cfg = app_config()
        if cfg.embedding_url is None:
            embedding_service = "unconfigured"
        else:
            try:
                fetch_vector(cfg.embedding_url, "probe")
                embedding_service = "reachable"
            except EmbeddingUnavailable:
                embedding_service = "unreachable"

        return {
            "database_connected": database_connected,
            "open_cascades": open_cascades,
            "embedding_service": embedding_service,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_info_metadata(cls)
