"""Expected OpenAPI contract suite (CR-7 G-008/T-001/A-002, C-011).

Exercises plan_manager.pipeline_checks.expected_openapi: the contract builds,
every closed vocabulary is pinned with the correct literal values, a clean
self-projection diffs empty, and planted divergences (renamed param, missing
enum value, extra command) each produce the exact expected divergence path.
No subprocess runs, no live server, no database.
"""

from __future__ import annotations

import copy

from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY
from plan_manager.pipeline_checks import expected_openapi as eo


# ---------------------------------------------------------------------------
# The contract builds.
# ---------------------------------------------------------------------------


def test_expected_contract_builds() -> None:
    contract = eo.build_expected_contract()
    assert set(contract) == {
        "paths", "commands", "vocabularies", "error_codes",
        "protocol_error_codes", "response_envelope",
    }
    assert contract["paths"] == {"/cmd": {"methods": ["post"]}}
    assert set(contract["commands"]) == set(INVENTORY)
    assert len(contract["commands"]) == len(INVENTORY)


def test_every_command_has_a_type_and_required_flag_per_param() -> None:
    contract = eo.build_expected_contract()
    for name, entry in contract["commands"].items():
        for param_name, param in entry["params"].items():
            assert param.get("type"), f"{name}.{param_name} missing type"
            assert isinstance(param.get("required"), bool), f"{name}.{param_name} missing required flag"


# ---------------------------------------------------------------------------
# Part (a): closed vocabularies pinned with literal values.
# ---------------------------------------------------------------------------

_EXPECTED_VOCABULARY_SIZES = {
    "bug_kind": 14,
    "bug_severity": 5,
    "bug_status": 11,
    "todo_status": 6,
    "wish_kind": 7,
    "wish_status": 7,
    "calendar_entry_status": 4,
    "runtime_link_type": 8,
}


def test_closed_vocabularies_cover_the_pinned_set() -> None:
    assert {v.name for v in eo.CLOSED_VOCABULARIES} == set(_EXPECTED_VOCABULARY_SIZES)


def test_closed_vocabulary_sizes_match_c011_seeds() -> None:
    for vocabulary in eo.CLOSED_VOCABULARIES:
        assert len(vocabulary.pinned_values) == _EXPECTED_VOCABULARY_SIZES[vocabulary.name], vocabulary.name


def test_closed_vocabulary_literal_pin_matches_live_domain_enum() -> None:
    """The literal pin must agree with the domain Enum it pins today.

    This is the guard the module docstring describes: pinned_values is a
    hand-copied literal, domain_values is imported live from the Enum. If
    someone edits a domain Enum without updating this module's pin, this is
    the assertion that goes red.
    """
    for vocabulary in eo.CLOSED_VOCABULARIES:
        assert vocabulary.pinned_values == vocabulary.domain_values, vocabulary.name


def test_expected_contract_vocabularies_section_matches_pinned_values() -> None:
    contract = eo.build_expected_contract()
    for vocabulary in eo.CLOSED_VOCABULARIES:
        assert sorted(contract["vocabularies"][vocabulary.name]) == sorted(vocabulary.pinned_values)


def test_every_vocabulary_carrier_references_a_real_command_and_param() -> None:
    contract = eo.build_expected_contract()
    for carrier in eo.VOCABULARY_CARRIERS:
        assert carrier.vocabulary in {v.name for v in eo.CLOSED_VOCABULARIES}
        assert carrier.command in contract["commands"], carrier.command
        assert carrier.param in contract["commands"][carrier.command]["params"], (carrier.command, carrier.param)
        assert carrier.enum_state in {"full", "subset", "absent"}
        if carrier.enum_state == "subset":
            assert carrier.expected_values
            vocabulary = next(v for v in eo.CLOSED_VOCABULARIES if v.name == carrier.vocabulary)
            assert carrier.expected_values <= vocabulary.pinned_values


def test_full_state_carrier_schema_already_declares_the_pinned_enum() -> None:
    """Every "full"-pinned carrier (runtime_link_add.link_type, bug_create.kind,
    ...): the live schema must agree today."""
    contract = eo.build_expected_contract()
    full_carriers = [c for c in eo.VOCABULARY_CARRIERS if c.enum_state == "full"]
    assert full_carriers, "expected at least one full-state carrier"
    for carrier in full_carriers:
        vocabulary = next(v for v in eo.CLOSED_VOCABULARIES if v.name == carrier.vocabulary)
        live_enum = contract["commands"][carrier.command]["params"][carrier.param].get("enum")
        assert live_enum == sorted(vocabulary.pinned_values), carrier.command


# ---------------------------------------------------------------------------
# Part (b): unified create-parameter-vocabulary pin (bug b230a02b).
# ---------------------------------------------------------------------------


def test_create_shape_pins_cover_todo_wish_bug() -> None:
    assert {p.command for p in eo.CREATE_SHAPE_PINS} == {"todo_create", "wish_create", "bug_create"}


def test_todo_and_wish_create_share_the_unified_description_and_anchor_shape() -> None:
    contract = eo.build_expected_contract()
    for command in ("todo_create", "wish_create"):
        pin = next(p for p in eo.CREATE_SHAPE_PINS if p.command == command)
        assert not pin.is_known_exception
        assert pin.description_fields == frozenset(eo.UNIFIED_DESCRIPTION_FIELDS)
        assert pin.anchor_fields == frozenset(eo.UNIFIED_ANCHOR_FIELDS)
        params = set(contract["commands"][command]["params"])
        assert pin.description_fields <= params
        assert pin.anchor_fields <= params


def test_bug_create_known_exception_is_recorded_and_green_today() -> None:
    """bug b230a02b: bug_create's divergent shape is a documented, GREEN exception."""
    contract = eo.build_expected_contract()
    pin = next(p for p in eo.CREATE_SHAPE_PINS if p.command == "bug_create")
    assert pin.is_known_exception
    assert pin.description_fields == frozenset({"short_description", "detailed_description"})
    assert "description" not in pin.description_fields
    params = set(contract["commands"]["bug_create"]["params"])
    # The pin's own claimed fields are actually present in the live schema...
    assert pin.description_fields <= params
    assert pin.anchor_fields <= params
    # ...and bug_create still does NOT carry the unified shape (that is the
    # point of the exception: this stays true until the unification lands).
    assert "description" not in params
    assert not (frozenset(eo.UNIFIED_ANCHOR_FIELDS) <= params)


# ---------------------------------------------------------------------------
# Part (c): error-code vocabulary.
# ---------------------------------------------------------------------------


def test_expected_error_codes_pin_matches_live_domain_codes() -> None:
    assert eo.EXPECTED_DOMAIN_ERROR_CODES == DOMAIN_CODES


def test_protocol_error_codes_include_the_domain_server_error_code() -> None:
    assert -32000 in eo.PROTOCOL_ERROR_CODES
    assert set(eo.PROTOCOL_ERROR_CODES) == {-32700, -32600, -32601, -32602, -32603, -32000}


# ---------------------------------------------------------------------------
# Self-projection: compare against the schema the shipped code would serve.
# ---------------------------------------------------------------------------


def test_self_projection_matches_expected_contract_exactly() -> None:
    divergences = eo.compare_live_schema(eo.project_self_schema())
    assert divergences == [], divergences


def test_self_projection_is_independent_of_build_expected_contract_object_identity() -> None:
    # Two independent calls must be structurally equal but need not be the
    # same object -- a sanity check that nothing is cached/mutated in place.
    first = eo.project_self_schema()
    second = eo.project_self_schema()
    assert first == second
    assert first is not second


# ---------------------------------------------------------------------------
# Planted divergences: each produces the exact expected divergence path.
# ---------------------------------------------------------------------------


def test_planted_divergence_renamed_param() -> None:
    live = eo.project_self_schema()
    live["commands"]["bug_create"]["params"]["kind_renamed"] = live["commands"]["bug_create"]["params"].pop("kind")
    live["commands"]["bug_create"]["required"] = [
        "kind_renamed" if name == "kind" else name for name in live["commands"]["bug_create"]["required"]
    ]
    divergences = eo.compare_live_schema(live)
    assert "commands.bug_create.params.kind: missing" in divergences
    assert "commands.bug_create.params.kind_renamed: unexpected" in divergences


def test_planted_divergence_missing_enum_value() -> None:
    live = eo.project_self_schema()
    full_enum = live["commands"]["runtime_link_add"]["params"]["link_type"]["enum"]
    truncated = [value for value in full_enum if value != "blocks"]
    live["commands"]["runtime_link_add"]["params"]["link_type"]["enum"] = truncated
    divergences = eo.compare_live_schema(live)
    expected_path = (
        "commands.runtime_link_add.params.link_type.enum: "
        f"expected={sorted(full_enum)!r} actual={sorted(truncated)!r}"
    )
    assert expected_path in divergences
    carrier_path_prefix = "vocabulary_carriers.runtime_link_type.runtime_link_add.link_type.enum:"
    assert any(d.startswith(carrier_path_prefix) for d in divergences)


def test_planted_divergence_extra_command() -> None:
    live = eo.project_self_schema()
    live["commands"]["totally_fake_command"] = {
        "params": {}, "required": [], "return_type": "object",
    }
    divergences = eo.compare_live_schema(live)
    assert "commands.totally_fake_command: unexpected" in divergences


def test_planted_divergence_missing_command() -> None:
    live = eo.project_self_schema()
    del live["commands"]["wish_create"]
    divergences = eo.compare_live_schema(live)
    assert "commands.wish_create: missing" in divergences


def test_planted_divergence_vocabulary_value_removed() -> None:
    live = eo.project_self_schema()
    live["vocabularies"]["bug_kind"] = [v for v in live["vocabularies"]["bug_kind"] if v != "security"]
    divergences = eo.compare_live_schema(live)
    assert any(d.startswith("vocabularies.bug_kind:") for d in divergences)


def test_planted_divergence_error_code_removed() -> None:
    live = eo.project_self_schema()
    live["error_codes"] = [c for c in live["error_codes"] if c != "PLAN_NOT_FOUND"]
    divergences = eo.compare_live_schema(live)
    assert any(d.startswith("error_codes: missing=") and "PLAN_NOT_FOUND" in d for d in divergences)


def test_planted_divergence_required_flag_changed() -> None:
    live = eo.project_self_schema()
    live["commands"]["bug_create"]["params"]["kind"]["required"] = False
    divergences = eo.compare_live_schema(live)
    assert "commands.bug_create.params.kind.required: expected=True actual=False" in divergences


def test_clean_deep_copy_still_diffs_empty() -> None:
    """A structurally-identical deep copy (not the same object) must still diff clean."""
    live = copy.deepcopy(eo.project_self_schema())
    assert eo.compare_live_schema(live) == []
