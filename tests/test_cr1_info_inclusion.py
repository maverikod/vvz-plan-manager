"""Contract test for CR-1 C-014: the six new commands must be visible in
info's agent_reference output (not just registered in INVENTORY).

escalation_get, escalation_list, model_binding_update, relation_update,
project_dependency_update, and project_dependency_confirm are new surface
commands (CR-1 MissingSurfaceCommands, C-010) that close entity read/update
gaps. This test guards the agent_reference tables -- status_vocabularies,
crud_matrix, and the command_index/_COMMAND_CATEGORIES category index -- that
this TS's changes add them to, so agent_reference stays the single source of
operational truth for the whole command surface (C-014).
"""

from __future__ import annotations

import json

from plan_manager.commands.info_reference_agents import agent_reference

_NEW_COMMANDS = [
    "escalation_get",
    "escalation_list",
    "model_binding_update",
    "relation_update",
    "project_dependency_update",
    "project_dependency_confirm",
]

def test_new_commands_appear_in_agent_reference_json() -> None:
    """Every new command name is present somewhere in agent_reference()."""
    blob = json.dumps(agent_reference())
    missing = [name for name in _NEW_COMMANDS if name not in blob]
    assert not missing, f"new commands absent from agent_reference(): {missing}"

def test_escalation_read_commands_in_status_vocabularies_and_crud_matrix() -> None:
    ref = agent_reference()
    escalation_status_commands = ref["status_vocabularies"]["entities"]["escalation"]["commands"]
    assert "escalation_get" in escalation_status_commands
    assert "escalation_list" in escalation_status_commands
    escalation_crud = ref["crud_matrix"]["entities"]["escalation"]
    assert "escalation_get" in escalation_crud["read"]
    assert "escalation_list" in escalation_crud["read"]

def test_model_binding_update_in_crud_matrix_and_category_index() -> None:
    ref = agent_reference()
    model_binding_crud = ref["crud_matrix"]["entities"]["model_binding"]
    assert "model_binding_update" in model_binding_crud["update"]
    model_binding_category = ref["command_index"]["categories"]["model_binding"]
    names = [entry["name"] for entry in model_binding_category]
    assert "model_binding_update" in names

def test_relation_update_in_crud_matrix_and_category_index() -> None:
    ref = agent_reference()
    relation_crud = ref["crud_matrix"]["entities"]["relation"]
    assert "relation_update" in relation_crud["update"]
    concept_relation_category = ref["command_index"]["categories"]["concept_relation"]
    names = [entry["name"] for entry in concept_relation_category]
    assert "relation_update" in names

def test_project_dependency_update_and_confirm_close_the_confidence_gap() -> None:
    ref = agent_reference()
    entity = ref["status_vocabularies"]["entities"]["project_dependency"]
    assert "project_dependency_update" in entity["commands"]
    assert "project_dependency_confirm" in entity["commands"]
    assert "no project_dependency_confirm command is exposed" not in entity["notes"]
    crud = ref["crud_matrix"]["entities"]["project_dependency"]
    assert "project_dependency_update" in crud["update"]
    assert "project_dependency_confirm" in crud["update"]
    category = ref["command_index"]["categories"]["project_dependency"]
    names = [entry["name"] for entry in category]
    assert "project_dependency_update" in names
    assert "project_dependency_confirm" in names

def test_agent_reference_still_json_serializable() -> None:
    json.dumps(agent_reference())
