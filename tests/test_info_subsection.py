"""Contract tests for info command selective subsection retrieval (C-014, T-006).

info already supports an optional `section` parameter that narrows the
response to one top-level section. This adds an optional `subsection`
parameter so an agent can fetch a single sub-key of that section's data (for
example one agent_reference table) without the whole section. subsection is
valid only together with section, and only for a key that exists in the
resolved section's own data; omitting subsection preserves the prior
whole-section behavior.
"""

from __future__ import annotations

import asyncio

import pytest
from mcp_proxy_adapter.commands.result import SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.info_reference_agents import agent_reference

def test_subsection_narrows_response_to_requested_table() -> None:
    result = asyncio.run(
        InfoCommand().execute(section="agent_reference", subsection="status_vocabularies")
    )

    assert isinstance(result, SuccessResult)
    assert result.data["section"] == "agent_reference"
    assert result.data["agent_reference"] == agent_reference()["status_vocabularies"]
    assert "lifecycle_matrices" not in result.data["agent_reference"]

def test_invalid_subsection_is_rejected() -> None:
    with pytest.raises(InvalidParamsError, match="Invalid subsection"):
        InfoCommand().validate_params(
            {"section": "agent_reference", "subsection": "not_a_real_table"}
        )

def test_subsection_without_section_is_rejected() -> None:
    with pytest.raises(InvalidParamsError, match="Invalid subsection"):
        InfoCommand().validate_params({"subsection": "status_vocabularies"})

def test_omitting_subsection_preserves_whole_section_behavior() -> None:
    result = asyncio.run(InfoCommand().execute(section="agent_reference"))

    assert isinstance(result, SuccessResult)
    assert result.data["section"] == "agent_reference"
    # assertion adjusted per L1 ruling 2026-07-16 — frozen A-002 authored
    # pre-G-004 crud_deletion_posture: InfoCommand._section_data augments the
    # agent_reference section with the crud_deletion_posture table, so the
    # whole-section payload is agent_reference() plus that one extra key.
    # assertion adjusted per L1 ruling 2026-07-16 — frozen CR-2 G-006/T-001/
    # A-002 mandate legitimately added export_delivery (via
    # export_delivery_agent_reference()) to the same section, a second
    # sanctioned augmentation on top of the whole-section payload.
    # assertion adjusted per L1 ruling 2026-07-16 — frozen CR-3 G-.../T-.../
    # A-... mandate legitimately added verification_observability (via
    # verification_observability_agent_reference()) to the same section, a
    # third sanctioned augmentation on top of the whole-section payload.
    # assertion adjusted per L1 ruling 2026-07-16 — CR-4 structure_integrity
    # wiring legitimately added structure_integrity (via
    # structure_integrity_agent_reference()) to the same section, a fourth
    # sanctioned augmentation on top of the whole-section payload.
    section = result.data["agent_reference"]
    assert "crud_deletion_posture" in section
    assert "export_delivery" in section
    assert "verification_observability" in section
    assert "structure_integrity" in section
    excluded = ("crud_deletion_posture", "export_delivery", "verification_observability", "structure_integrity")
    assert {k: v for k, v in section.items() if k not in excluded} == agent_reference()
    assert "status_vocabularies" in result.data["agent_reference"]
