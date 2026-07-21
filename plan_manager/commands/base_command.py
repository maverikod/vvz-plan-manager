"""Project-wide base ``Command`` fixing a vendored-adapter validation bug (bug
c72e047c-ad6b-4e02-825e-a0f6b8683149).

``mcp_proxy_adapter.commands.base.Command.validate_params`` (the vendored,
never-edited adapter package) treats *any* parameter whose value is Python
``None`` **or** a string that is case-insensitively equal to ``"null"``,
``"none"``, or ``""`` as equivalent to a missing parameter, and deletes it
from the params dict *before* the required-parameters check runs (see
``.venv/.../mcp_proxy_adapter/commands/base.py``, the loop just above the
``required`` check). That conflates a genuinely omitted/``null`` parameter
with a legitimate literal string value -- e.g. ``anchor_type="none"`` is a
real, documented member of
:class:`plan_manager.domain.primary_anchor.PrimaryAnchorType` (an unanchored
TODO/bug), yet the adapter rejected it with a misleading "Missing required
parameters" error identical to what an actually-omitted parameter produces.

Every ``plan_manager`` command subclasses :class:`Command` from *this*
module instead of the adapter's directly, so the fix applies uniformly
across the whole command surface without touching the vendored package.

Fix: only a true JSON ``null`` (Python ``None``) -- or a key genuinely absent
from ``params`` -- counts as "missing". Literal string values, including
``"none"``, ``"null"``, and ``""`` in any case, are preserved untouched and
reach schema/domain validation exactly as sent; a command whose domain does
not accept an empty string (or any other literal) for a given field is
expected to reject it itself, with a specific, non-misleading error, rather
than have it silently vanish before validation even runs.

All other ``validate_params`` duties (unknown-parameter rejection under
``additionalProperties: false``, per-property schema value checks, and the
required-parameters check itself) are preserved faithfully from the adapter;
this override changes only the "which values count as missing" step.
"""

from __future__ import annotations

from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command as _AdapterCommand
from mcp_proxy_adapter.core.errors import ValidationError
from mcp_proxy_adapter.core.logging import get_global_logger


class Command(_AdapterCommand):
    """Base class for every plan_manager command; see module docstring."""

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate command parameters.

        Args:
            params: Parameters to validate.

        Returns:
            Validated parameters.

        Raises:
            ValidationError: If parameters are invalid.
        """
        # Ensure params is a dictionary, even if None was passed
        if params is None:
            params = {}

        # Create a copy to avoid modifying the input dictionary during iteration
        validated_params = params.copy()

        # Handle true None (JSON null) parameters only. Unlike the vendored
        # adapter, literal string sentinels ("null"/"none"/"" in any case)
        # are NOT stripped here -- they are real values and must reach
        # schema/domain validation untouched (bug c72e047c).
        for key, value in list(validated_params.items()):
            if value is None:
                # For commands that specifically handle None values (like
                # help's cmdname), keep the parameter but ensure it's a
                # proper Python None.
                if key in [
                    "cmdname"
                ]:  # список параметров, для которых None является допустимым значением
                    validated_params[key] = None
                else:
                    # For most parameters, remove genuinely-null values to
                    # avoid issues.
                    del validated_params[key]

        # Get command schema to validate parameters
        schema = self.get_schema()
        if schema and "properties" in schema:
            allowed_properties = schema["properties"].keys()
            # Check additionalProperties setting (default: False for strict validation)
            additional_properties_allowed = schema.get("additionalProperties", False)

            # Find parameters that are not in the schema
            invalid_params = []
            for param_name in list(validated_params.keys()):
                if param_name not in allowed_properties:
                    invalid_params.append(param_name)

            # Handle invalid parameters based on additionalProperties setting
            if invalid_params:
                if additional_properties_allowed:
                    # Permissive mode: allow additional parameters, just log debug info.
                    # get_global_logger() is untyped in the vendored adapter package
                    # (out of scope to edit -- see module docstring).
                    get_global_logger().debug(  # type: ignore[no-untyped-call]
                        f"Command {self.__class__.__name__} received additional parameters: {invalid_params}. "
                        f"These are allowed due to additionalProperties: true"
                    )
                else:
                    # Strict mode: raise ValidationError for invalid parameters
                    raise ValidationError(
                        f"Invalid parameters: {', '.join(invalid_params)}. "
                        f"Allowed parameters: {list(allowed_properties)}",
                        data={"invalid_parameters": invalid_params},
                    )

            command_name = (
                self.name
                if hasattr(self, "name") and self.name
                else self.__class__.__name__
            )
            _AdapterCommand._validate_param_values_against_schema(
                validated_params, schema, command_name
            )

        # Validate required parameters based on command schema
        if schema and "required" in schema:
            required_params = schema["required"]
            missing_params = []

            for param in required_params:
                if param not in validated_params:
                    missing_params.append(param)

            if missing_params:
                raise ValidationError(
                    f"Missing required parameters: {', '.join(missing_params)}",
                    data={"missing_parameters": missing_params},
                )

        return validated_params
