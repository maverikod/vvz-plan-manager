import asyncio
import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.step_update_command import (
    StepUpdateCommand,
    _validate_concept_bindings,
    _validate_relations_field,
)
from plan_manager.views.coverage import relation_coverage


def test_step_update_schema_allows_concepts_without_fields() -> None:
    schema = StepUpdateCommand.get_schema()
    metadata = StepUpdateCommand.metadata()

    assert schema["required"] == ["plan", "step_id"]
    assert schema["properties"]["concepts"]["type"] == "array"
    assert metadata["parameters"]["fields"]["required"] is False
    assert metadata["parameters"]["concepts"]["required"] is False
    assert "INVALID_STEP_FIELD_SHAPE" in metadata["error_cases"]


def test_step_update_rejects_invalid_relations_shape() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        _validate_relations_field(
            {"relations": ["defines boundary for runtime work management"]}
        )

    assert excinfo.value.code == "INVALID_STEP_FIELD_SHAPE"
    assert excinfo.value.details["field"] == "fields.relations"
    assert excinfo.value.details["index"] == 0


def test_step_update_accepts_valid_relations_shape() -> None:
    relations = _validate_relations_field(
        {
            "relations": [
                {
                    "type": "uses",
                    "from_concept": "C-001",
                    "to_concept": "C-002",
                }
            ]
        }
    )

    assert relations == [
        {"type": "uses", "from_concept": "C-001", "to_concept": "C-002"}
    ]


def test_step_update_rejects_invalid_concepts_shape() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        _validate_concept_bindings(["C-001", "not-a-concept"])

    assert excinfo.value.code == "INVALID_STEP_FIELD_SHAPE"
    assert excinfo.value.details == {"field": "concepts", "index": 1}


def test_step_update_execute_rejects_empty_patch_with_domain_code() -> None:
    result = asyncio.run(StepUpdateCommand().execute(plan="p", step_id="G-001"))

    assert result.to_dict()["error"]["data"]["domain_code"] == "INVALID_STEP_FIELD_SHAPE"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _CoverageConn:
    def execute(self, query, _params):
        if "SELECT fields FROM step" in query:
            return _Rows([({"relations": ["bad relation"]},)])
        if "SELECT from_concept, to_concept, type FROM relation" in query:
            return _Rows([])
        raise AssertionError(query)


def test_relation_coverage_reports_invalid_shape_without_crashing() -> None:
    report = relation_coverage(_CoverageConn(), uuid.uuid4())

    assert report.missing == []
    assert report.extra == ["INVALID_RELATION_SHAPE"]
