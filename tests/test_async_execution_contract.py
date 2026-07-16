"""Executable contract for the uniform asynchronous-execution discipline (C-006).

Every heavy command on the plan_manager surface runs through one queued
discipline: its `use_queue` class attribute must exactly match its membership
in the single `_QUEUED_COMMANDS` declaration in
`plan_manager.commands.info_reference_agents`, and that same declared set must
be mirrored consistently into both the command catalog output
(`command_index()`) and the operational agent-reference
(`agent_reference()["queue_polling"]`). srt_snapshot_create (the known
proxy-timeout offender on large plans) is a required member of the set.
"""

from __future__ import annotations

from importlib import import_module

import pytest

from plan_manager.commands.info_reference_agents import (
    _QUEUED_COMMANDS,
    agent_reference,
    command_index,
)
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import _class_name
from plan_manager.commands.srt_snapshot_create_command import SrtSnapshotCreateCommand

def test_srt_snapshot_create_joined_the_queued_discipline() -> None:
    assert SrtSnapshotCreateCommand.use_queue is True
    assert "srt_snapshot_create" in _QUEUED_COMMANDS

@pytest.mark.parametrize("name", sorted(INVENTORY))
def test_declared_queued_set_matches_each_commands_use_queue_attribute(name: str) -> None:
    module = import_module(f"plan_manager.commands.{name}_command")
    cls = getattr(module, _class_name(name))
    declared = name in _QUEUED_COMMANDS
    actual = bool(getattr(cls, "use_queue", False))
    assert actual == declared, (
        f"{name}: use_queue={actual} but _QUEUED_COMMANDS membership={declared}; "
        "the single queued-command declaration must match every command's own "
        "use_queue class attribute exactly."
    )

def test_queued_set_is_mirrored_into_the_command_catalog_output() -> None:
    index = command_index()
    mirrored: set[str] = set()
    for entries in index["categories"].values():
        for entry in entries:
            assert "queued" in entry, f"catalog entry missing queued flag: {entry}"
            if entry["queued"]:
                mirrored.add(entry["name"])
            assert entry["queued"] == (entry["name"] in _QUEUED_COMMANDS)
    assert mirrored == set(_QUEUED_COMMANDS)

def test_queued_set_is_mirrored_into_the_operational_agent_reference() -> None:
    guide = agent_reference()["queue_polling"]
    assert set(guide["queued_commands"]) == set(_QUEUED_COMMANDS)
    assert guide["poll_command"] == "queue_get_job_status"
    assert guide["enqueue_acknowledgement"]["store"] == "queuemgr"
    assert guide["enqueue_acknowledgement"]["poll_with"] == "queue_get_job_status"
