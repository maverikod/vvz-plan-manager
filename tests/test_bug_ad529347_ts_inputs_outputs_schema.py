"""Regression tests for bug ad529347-925e-44c9-8b04-df9d82c07cb9.

Plan Manager accepted typed input/output objects for a level-4 (TS) step's
fields.inputs / fields.outputs, but step_update help, the level-4
context_common/context_bundle field_schema, and info's planning_standards
reference all documented those fields only as bare field names -- with no
nested item contract ({name, type, description}, type one of "input" or
"output"). The mechanical gate's own validation finding
("*.type must be a non-empty string") did not restate that shape either.
These tests pin the documentation/metadata/error-wording fix in place;
none of them change what step_update or the gate accept/reject.
"""

import uuid

from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.commands.step_update_metadata import get_step_update_metadata
from plan_manager.commands.info_reference import planning_standards_reference
from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_structure import check_parse_inputs_outputs
from plan_manager.views.context_blocks import (
    TS_INPUT_OUTPUT_ITEM_SCHEMA,
    _field_schema_block,
)

_TYPE_ENUM_MARKER = 'one of "input" or "output"'


def _step(level: int, step_id: str, fields: dict) -> Step:
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=uuid.uuid4(),
        parent_step_uuid=uuid.uuid4() if level != 3 else None,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree(steps: list[Step]) -> GateTree:
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


# --------------------------------------------------------------------------
# 1. step_update help/metadata documents the nested item contract.
# --------------------------------------------------------------------------


def test_step_update_metadata_documents_inputs_outputs_item_shape() -> None:
    metadata = get_step_update_metadata(StepUpdateCommand)

    assert _TYPE_ENUM_MARKER in metadata["detailed_description"]
    assert "name, type, description" in metadata["detailed_description"]
    assert any(
        _TYPE_ENUM_MARKER in practice for practice in metadata["best_practices"]
    ), metadata["best_practices"]


def test_step_update_metadata_has_valid_and_invalid_inputs_outputs_examples() -> None:
    metadata = get_step_update_metadata(StepUpdateCommand)
    examples = metadata["usage_examples"]

    valid = next(
        (
            ex
            for ex in examples
            if ex["description"].startswith("VALID")
            and "inputs" in ex["command"].get("fields", {})
        ),
        None,
    )
    invalid = next((ex for ex in examples if ex["description"].startswith("INVALID")), None)

    assert valid is not None, examples
    valid_item = valid["command"]["fields"]["inputs"][0]
    assert set(valid_item) == {"name", "type", "description"}
    assert valid_item["type"] in ("input", "output")

    assert invalid is not None, examples
    invalid_items = invalid["command"]["fields"]["inputs"]
    assert all(isinstance(item, str) for item in invalid_items)
    assert _TYPE_ENUM_MARKER in invalid["explanation"]


# --------------------------------------------------------------------------
# 2. context_common/context_bundle field_schema (level 4) includes the item
#    schema; other levels are untouched.
# --------------------------------------------------------------------------


def test_field_schema_block_level4_includes_item_schemas() -> None:
    block = _field_schema_block(4)

    schema = block["schema"]
    assert "inputs" in schema["required_fields"]
    assert "outputs" in schema["required_fields"]
    item_schemas = schema["item_schemas"]
    assert item_schemas["inputs"] == TS_INPUT_OUTPUT_ITEM_SCHEMA
    assert item_schemas["outputs"] == TS_INPUT_OUTPUT_ITEM_SCHEMA
    assert item_schemas["inputs"]["required"] == ["name", "type", "description"]
    assert _TYPE_ENUM_MARKER in str(item_schemas["inputs"]["properties"]["type"])


def test_field_schema_block_levels_3_and_5_have_no_item_schemas() -> None:
    for level in (3, 5):
        schema = _field_schema_block(level)["schema"]
        assert "item_schemas" not in schema


# --------------------------------------------------------------------------
# 3. info's planning_standards reference carries the same contract for TS.
# --------------------------------------------------------------------------


def test_planning_standards_ts_includes_item_schemas() -> None:
    reference = planning_standards_reference()
    ts = reference["artifact_levels"]["TS"]

    assert "inputs" in ts["required_shape"]
    assert "outputs" in ts["required_shape"]
    assert ts["item_schemas"]["inputs"] == TS_INPUT_OUTPUT_ITEM_SCHEMA
    assert ts["item_schemas"]["outputs"] == TS_INPUT_OUTPUT_ITEM_SCHEMA


def test_planning_standards_gs_and_as_have_no_item_schemas() -> None:
    reference = planning_standards_reference()
    assert "item_schemas" not in reference["artifact_levels"]["GS"]
    assert "item_schemas" not in reference["artifact_levels"]["AS"]


# --------------------------------------------------------------------------
# 4. The mechanical gate's parse.inputs_outputs finding states the expected
#    shape and allowed type values; the check's accept/reject behavior is
#    unchanged (still a plain non-empty-string check on "type").
# --------------------------------------------------------------------------


def test_gate_inputs_outputs_message_states_expected_shape_and_type_values() -> None:
    step = _step(
        4,
        "T-001",
        fields={
            "inputs": [{"name": "foo", "type": "", "description": "bar"}],
            "outputs": [],
        },
    )
    tree = _tree([step])

    findings = check_parse_inputs_outputs(tree, [step])

    type_findings = [f for f in findings if f.message.startswith("inputs[0].type")]
    assert len(type_findings) == 1
    message = type_findings[0].message
    assert "must be a non-empty string" in message
    assert "{name, type, description}" in message
    assert _TYPE_ENUM_MARKER in message


def test_gate_inputs_outputs_still_accepts_any_non_empty_type_string() -> None:
    """Documentation-only fix: an out-of-enum but non-empty type string
    (e.g. "banana") is still NOT rejected -- write-boundary enum enforcement
    is explicitly out of scope for bug ad529347 (tracked separately)."""
    step = _step(
        4,
        "T-002",
        fields={
            "inputs": [{"name": "foo", "type": "banana", "description": "bar"}],
            "outputs": [],
        },
    )
    tree = _tree([step])

    findings = check_parse_inputs_outputs(tree, [step])

    assert findings == []


def test_gate_inputs_outputs_reports_object_shape_error_for_string_items() -> None:
    step = _step(4, "T-003", fields={"inputs": ["bare-string-item"], "outputs": []})
    tree = _tree([step])

    findings = check_parse_inputs_outputs(tree, [step])

    assert len(findings) == 1
    assert findings[0].message == "inputs[0] must be an object"
