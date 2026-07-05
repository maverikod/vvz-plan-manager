"""Server self-description command (C-025)."""
from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.info_metadata import get_info_metadata
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.runtime.build_info import build_info, operator_doc
from plan_manager.scoring.embedding import EmbeddingUnavailable, fetch_vector


class InfoCommand(Command):
    """Server self-description command (C-025).

    Read-only command implementing CommandContract (C-023). Returns
    identity, build metadata, a runtime summary with database and
    embedding service probes and the open cascade count, and the
    embedded operator documentation text. An optional "section"
    parameter restricts the answer to exactly one of these four parts.
    """

    name = "info"
    version = "1.0.0"
    descr = (
        "Return the server self-description: identity, build metadata, "
        "runtime summary, and operator documentation."
    )
    category = "system"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for the info command.

        Returns:
            Dict[str, Any]: JSON-schema-shaped dictionary with one
            optional "section" property restricted to four enumerated
            values, an empty required list, and additionalProperties
            set to False.
        """
        return {
            "type": "object",
            "properties": {
                "section": {
                    "type": "string",
                    "description": (
                        "Restrict the response to one section: "
                        "'identity', 'build', 'runtime', or "
                        "'documentation'. Omitting this parameter "
                        "returns all four sections."
                    ),
                    "enum": [
                        "identity",
                        "build",
                        "runtime",
                        "documentation",
                    ],
                },
            },
            "required": [],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate parameters for the info command.

        Calls the base class validation first (structural checks against
        get_schema's JSON-schema-shaped output), then re-checks that the
        optional "section" parameter, if present, is one of the four
        allowed section names. This re-check is a semantic safety net:
        schema-level enum enforcement by the platform validator is
        shallow, so this command re-verifies membership itself. An
        invalid value raises ValueError, which the platform adapter maps
        to an invalid-params response; this command never raises a
        domain error code for a malformed parameter.

        Args:
            params: Raw parameter dictionary as received by the command,
                before semantic validation.

        Returns:
            Dict[str, Any]: The validated parameter dictionary, unchanged
            from what the base class validation returns.

        Raises:
            ValueError: If "section" is present in params and is not one
                of "identity", "build", "runtime", "documentation".
        """
        params = super().validate_params(params)
        section = params.get("section")
        if section is not None and section not in (
            "identity",
            "build",
            "runtime",
            "documentation",
        ):
            raise ValueError(
                f"Invalid section: {section!r}. Must be one of "
                "'identity', 'build', 'runtime', 'documentation'."
            )
        return params

    async def execute(
        self,
        section: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Assemble and return the server self-description.

        Builds four parts from embedded package data and live runtime
        probes: identity, build, runtime, documentation. When section is
        given, only that part is returned, nested under a "section" key
        alongside the requested section name. When section is None, all
        four parts are returned together. Any unexpected exception,
        including a missing embedded documentation payload surfaced by
        operator_doc() as RuntimeError, is caught by the final handler
        and mapped to a platform ErrorResult via map_exception; this
        command never raises a domain error code of its own.

        Args:
            section: Optional section selector, one of "identity",
                "build", "runtime", "documentation". None returns all
                four sections. Already validated by validate_params.

        Returns:
            SuccessResult | ErrorResult: SuccessResult wrapping the
            assembled data dictionary, or an ErrorResult produced by
            map_exception when an unexpected exception occurs.
        """
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
                        cur.execute(
                            "SELECT count(*) FROM cascade WHERE status = 'open'"
                        )
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

            runtime = {
                "database_connected": database_connected,
                "open_cascades": open_cascades,
                "embedding_service": embedding_service,
            }

            documentation = {"text": operator_doc()}

            parts: Dict[str, Any] = {
                "identity": identity,
                "build": build,
                "runtime": runtime,
                "documentation": documentation,
            }

            if section is not None:
                data: Dict[str, Any] = {"section": section, section: parts[section]}
            else:
                data = parts

            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return extended documentation metadata for this command.

        Delegates to get_info_metadata, which builds the full
        documentation dictionary from this class's own identity
        attributes (name, version, descr, category, author, email).

        Returns:
            Dict[str, Any]: metadata dictionary produced by
            get_info_metadata(cls); see get_info_metadata's own
            docstring in plan_manager/commands/info_metadata.py for the
            exact key set (name, version, description, category,
            author, email, detailed_description, parameters,
            return_value, usage_examples, error_cases, best_practices).
        """
        return get_info_metadata(cls)
