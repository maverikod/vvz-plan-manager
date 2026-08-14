"""Regression tests for bug b230a02b (kind enum discoverability + evidence
convention).

Before this fix, bug_create's `kind` schema property documented the legal
BugKind values only in free text (the expected_openapi "absent" carrier
state); a caller (or generic schema-driven UI) had no machine-checkable way
to discover the valid set short of trial and error against
domain.bug_report.validate_bug_kind. The fix adds a JSON-schema `enum` to
`kind` on bug_create (mirroring the existing `runtime_link_add.link_type`
"full" pattern), and clarifies the free-form-JSON `evidence` parameter's
description with the `{"text": ...}` wrapping convention on both bug_create
and bug_update.

Pure unit tests: schema inspection only, no db connection, no live server.
"""

from __future__ import annotations

from plan_manager.commands.bug_create_command import BugCreateCommand
from plan_manager.commands.bug_update_command import BugUpdateCommand
from plan_manager.domain.bug_report import BUG_KINDS
from plan_manager.pipeline_checks import expected_openapi as eo


def test_bug_create_kind_schema_declares_the_full_sorted_enum() -> None:
    schema = BugCreateCommand.get_schema()
    kind_prop = schema["properties"]["kind"]
    assert kind_prop.get("enum") == sorted(BUG_KINDS)


def test_bug_create_evidence_description_carries_text_wrapping_convention() -> None:
    schema = BugCreateCommand.get_schema()
    evidence_descr = schema["properties"]["evidence"]["description"]
    assert '{"text"' in evidence_descr


def test_bug_update_evidence_description_carries_text_wrapping_convention() -> None:
    schema = BugUpdateCommand.get_schema()
    evidence_descr = schema["properties"]["evidence"]["description"]
    assert '{"text"' in evidence_descr


def test_bug_update_has_no_kind_property() -> None:
    """bug_update never mutates kind (no such schema property exists); the
    enum-discoverability fix therefore applies only to bug_create's kind."""
    schema = BugUpdateCommand.get_schema()
    assert "kind" not in schema["properties"]


def test_expected_openapi_bug_kind_carrier_is_pinned_full_and_self_projection_stays_green() -> None:
    """The expected_openapi VOCABULARY_CARRIERS pin for bug_create.kind must
    have flipped from "absent" to "full", and the live schema must agree
    with the pinned bug_kind vocabulary (self-projection green, no drift)."""
    carrier = next(c for c in eo.VOCABULARY_CARRIERS if c.command == "bug_create" and c.param == "kind")
    assert carrier.enum_state == "full"

    contract = eo.build_expected_contract()
    vocabulary = next(v for v in eo.CLOSED_VOCABULARIES if v.name == "bug_kind")
    live_enum = contract["commands"]["bug_create"]["params"]["kind"].get("enum")
    assert live_enum == sorted(vocabulary.pinned_values)

    live = eo.project_self_schema()
    divergences = eo.compare_live_schema(live)
    assert divergences == []
