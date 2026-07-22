"""Regression tests for bug 761ee3dd (documentation, critical).

step-addressing commands accept a step reference as a UUID, a canonical
path (e.g. G-001/T-002/A-001), or a bare local step id -- and reject an
ambiguous bare id (resolve_step_ref in plan_manager/commands/step_ref.py)
with AMBIGUOUS_STEP_ID (or AMBIGUOUS_PARENT_STEP_ID for a parent/
new-parent reference). That resolution and rejection behavior already
shipped and is covered by tests/test_step_ref.py; THIS file guards only
the DOCUMENTATION side of the bug: every audited command's schema and
extended metadata must (a) name all three selector forms in the
step-addressing parameter's description, and (b) list the ambiguity
error code in error_cases so an agent reading help() output learns of
the rejection without tripping over it live first.
"""

from __future__ import annotations

from importlib import import_module

import pytest


def _class_name(command_name: str) -> str:
    """Convert a snake_case command name to its Command class name.

    Args:
        command_name: Snake_case command name as it appears in the
            normative INVENTORY (e.g. "step_get").

    Returns:
        The PascalCase class name plan_manager uses for that command's
        Command subclass (e.g. "StepGetCommand"), matching the same
        convention tests/test_error_code_reachability_contract.py relies on.
    """
    return "".join(part.capitalize() for part in command_name.split("_")) + "Command"


def _load_command_class(command_name: str):
    """Import and return the Command subclass for one command by name.

    Args:
        command_name: Snake_case command name (module is
            plan_manager.commands.<command_name>_command).

    Returns:
        The Command subclass object for the given command name.
    """
    module = import_module(f"plan_manager.commands.{command_name}_command")
    return getattr(module, _class_name(command_name))


# (command_name, step-addressing parameter name, ambiguous error code that
# parameter's resolution can raise). Covers every resolve_step_ref call
# site audited under bug 761ee3dd: step_get/delete/set_status/update
# (step_id), step_move (step_id + new_parent_step_id), the three graph_*
# commands (step_id), step_create (parent_step_id), step_list (parent,
# metadata only -- its schema already documented the forms), step_transition
# (step_id), context_common/context_bundle (node, via the shared
# context_block_metadata ERROR_CASES), and step_runtime_get/report
# (step_id, via views/step_runtime_scope.resolve_step_by_id).
SELECTOR_PARAM_CASES: list[tuple[str, str, str]] = [
    ("step_get", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_delete", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_move", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_move", "new_parent_step_id", "AMBIGUOUS_PARENT_STEP_ID"),
    ("step_set_status", "step_id", "AMBIGUOUS_STEP_ID"),
    ("graph_deps", "step_id", "AMBIGUOUS_STEP_ID"),
    ("graph_dependents", "step_id", "AMBIGUOUS_STEP_ID"),
    ("graph_impact", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_create", "parent_step_id", "AMBIGUOUS_PARENT_STEP_ID"),
    ("step_list", "parent", "AMBIGUOUS_STEP_ID"),
    ("step_update", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_transition", "step_id", "AMBIGUOUS_STEP_ID"),
    ("context_common", "node", "AMBIGUOUS_STEP_ID"),
    ("context_bundle", "node", "AMBIGUOUS_STEP_ID"),
    ("step_runtime_get", "step_id", "AMBIGUOUS_STEP_ID"),
    ("step_runtime_report", "step_id", "AMBIGUOUS_STEP_ID"),
]


def _names_all_selector_forms(description: str) -> bool:
    """True iff a parameter description names UUID and a path/unambiguous marker."""
    lowered = description.lower()
    return "uuid" in lowered and ("canonical path" in lowered or "unambiguous" in lowered)


@pytest.mark.parametrize("command_name,param_name,ambiguous_code", SELECTOR_PARAM_CASES)
def test_metadata_parameter_documents_all_selector_forms(
    command_name: str, param_name: str, ambiguous_code: str
) -> None:
    """metadata()['parameters'][param_name] names UUID + canonical path/unambiguous."""
    cls = _load_command_class(command_name)
    metadata = cls.metadata()
    description = metadata["parameters"][param_name]["description"]
    assert _names_all_selector_forms(description), (
        f"{command_name}.{param_name}: metadata description does not name all "
        f"selector forms: {description!r}"
    )


@pytest.mark.parametrize("command_name,param_name,ambiguous_code", SELECTOR_PARAM_CASES)
def test_schema_parameter_documents_all_selector_forms(
    command_name: str, param_name: str, ambiguous_code: str
) -> None:
    """get_schema()['properties'][param_name] names UUID + canonical path/unambiguous."""
    cls = _load_command_class(command_name)
    schema = cls.get_schema()
    description = schema["properties"][param_name]["description"]
    assert _names_all_selector_forms(description), (
        f"{command_name}.{param_name}: schema description does not name all "
        f"selector forms: {description!r}"
    )


@pytest.mark.parametrize("command_name,param_name,ambiguous_code", SELECTOR_PARAM_CASES)
def test_metadata_error_cases_documents_ambiguous_code(
    command_name: str, param_name: str, ambiguous_code: str
) -> None:
    """metadata()['error_cases'] lists the ambiguity code this selector can raise."""
    cls = _load_command_class(command_name)
    metadata = cls.metadata()
    assert ambiguous_code in metadata["error_cases"], (
        f"{command_name}: error_cases is missing {ambiguous_code} for selector "
        f"parameter {param_name!r}: {sorted(metadata['error_cases'])}"
    )


def test_context_compile_include_documents_step_definition_of_ambiguity() -> None:
    """context_compile's include.step_definition_of resolves via resolve_step_ref
    too (views/context_blocks.compile_context); its object-typed 'include'
    parameter description must still name the selector forms and the
    ambiguous code, and the shared error_cases (context_block_metadata.
    ERROR_CASES) must list AMBIGUOUS_STEP_ID."""
    cls = _load_command_class("context_compile")
    metadata = cls.metadata()
    description = metadata["parameters"]["include"]["description"]
    assert _names_all_selector_forms(description), description
    assert "AMBIGUOUS_STEP_ID" in metadata["error_cases"]

    schema = cls.get_schema()
    schema_description = schema["properties"]["include"]["description"]
    assert _names_all_selector_forms(schema_description), schema_description


def test_step_dependency_family_already_documents_selector_forms_and_ambiguity() -> None:
    """Not a fix target (already correct pre-existing documentation) --
    guards against regressing the step_dependency_* command family's
    already-good step_id/depends_on selector wording and AMBIGUOUS_STEP_ID
    error_cases entries while this bug's fixes are being made elsewhere."""
    for command_name in (
        "step_dependency_add",
        "step_dependency_clear",
        "step_dependency_list",
        "step_dependency_remove",
        "step_dependency_set",
        "step_dependency_apply",
        "step_dependency_preview",
    ):
        cls = _load_command_class(command_name)
        metadata = cls.metadata()
        assert "AMBIGUOUS_STEP_ID" in metadata["error_cases"], command_name
