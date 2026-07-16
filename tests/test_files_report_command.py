import uuid

from mcp_proxy_adapter.commands.command_help_info import build_command_help_payload

from plan_manager.commands.files_report_command import FilesReportCommand
from plan_manager.domain.step import Step
from plan_manager.views.files_report import (
    build_files_report,
    has_ordering_path,
    reachable_from,
)

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")

def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    target_file: str = "",
    operation: str = "modify_file",
    priority: int = 1,
) -> Step:
    fields: dict = {}
    if level == 5:
        fields = {"target_file": target_file, "operation": operation, "priority": priority}
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )

def test_files_report_schema_and_metadata_are_help_ready() -> None:
    schema = FilesReportCommand.get_schema()
    payload = build_command_help_payload("files_report", FilesReportCommand, "custom")

    assert FilesReportCommand.use_queue is False
    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["scope"]["default"] == "whole_plan"
    assert schema["properties"]["limit"]["maximum"] == 200
    assert payload["ai_metadata"]["parameters"]["scope"]["required"] is False
    assert payload["ai_metadata"]["error_cases"]["INVALID_SCOPE"]
    assert "FilesWriterReport" in payload["ai_metadata"]["detailed_description"]

def test_reachable_from_follows_edges_forward_only() -> None:
    a = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    b = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
    c = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
    edges = {(a, b), (b, c)}

    assert reachable_from(a, edges) == {b, c}
    assert reachable_from(c, edges) == set()

def test_has_ordering_path_true_for_direct_and_transitive_edges() -> None:
    a = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
    b = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
    c = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
    edges = {(a, b), (b, c)}

    assert has_ordering_path(a, b, edges) is True
    assert has_ordering_path(a, c, edges) is True
    assert has_ordering_path(b, a, edges) is True

def test_has_ordering_path_false_when_no_path_either_direction() -> None:
    a = uuid.UUID("00000000-0000-0000-0000-0000000000a3")
    b = uuid.UUID("00000000-0000-0000-0000-0000000000b3")
    edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    assert has_ordering_path(a, b, edges) is False

def test_build_files_report_groups_by_file_sorts_by_priority_and_sorts_files() -> None:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid)
    a1 = _step(
        "00000000-0000-0000-0000-000000000013", 5, "A-002", ts.uuid,
        target_file="b.py", operation="modify_file", priority=2,
    )
    a2 = _step(
        "00000000-0000-0000-0000-000000000014", 5, "A-001", ts.uuid,
        target_file="b.py", operation="create_file", priority=1,
    )
    a3 = _step(
        "00000000-0000-0000-0000-000000000015", 5, "A-003", ts.uuid,
        target_file="a.py", operation="create_file", priority=1,
    )
    nodes = {step.uuid: step for step in (gs, ts, a1, a2, a3)}
    edges = {(a2.uuid, a1.uuid)}

    report = build_files_report(nodes, [a1, a2, a3], edges)

    assert [entry["target_file"] for entry in report] == ["a.py", "b.py"]
    b_entry = report[1]
    assert [w["step"] for w in b_entry["writers"]] == [
        "G-001/T-001/A-001",
        "G-001/T-001/A-002",
    ]
    assert b_entry["ordering_conflict"] is False
    a_entry = report[0]
    assert a_entry["writers"] == [
        {"step": "G-001/T-001/A-003", "priority": 1, "operation": "create_file"}
    ]
    assert a_entry["ordering_conflict"] is False

def test_build_files_report_flags_ordering_conflict_with_no_path_between_writers() -> None:
    gs = _step("00000000-0000-0000-0000-000000000021", 3, "G-001", None)
    ts1 = _step("00000000-0000-0000-0000-000000000022", 4, "T-001", gs.uuid)
    ts2 = _step("00000000-0000-0000-0000-000000000023", 4, "T-002", gs.uuid)
    a1 = _step(
        "00000000-0000-0000-0000-000000000024", 5, "A-001", ts1.uuid,
        target_file="shared.py", operation="create_file", priority=1,
    )
    a2 = _step(
        "00000000-0000-0000-0000-000000000025", 5, "A-001", ts2.uuid,
        target_file="shared.py", operation="modify_file", priority=1,
    )
    nodes = {step.uuid: step for step in (gs, ts1, ts2, a1, a2)}
    edges: set[tuple[uuid.UUID, uuid.UUID]] = set()

    report = build_files_report(nodes, [a1, a2], edges)

    assert len(report) == 1
    assert report[0]["target_file"] == "shared.py"
    assert report[0]["ordering_conflict"] is True
