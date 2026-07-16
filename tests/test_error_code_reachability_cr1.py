"""Error-code reachability contract: every documented error-case code is a registered domain
code, and the typed guard/exception -> map_exception -> domain_code pipeline for CR1's
error-code-fidelity work actually reaches the code it claims to reach (T-004)."""

from __future__ import annotations

import uuid
from importlib import import_module

import pytest

from plan_manager.commands.errors import DOMAIN_CODES, DomainCommandError, map_exception
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.model_binding_command_metadata import MODEL_ERROR_CASES
from plan_manager.commands.project_dependency_add_command import ProjectDependencyAddCommand
from plan_manager.commands.todo_link_add_command import TodoLinkAddCommand
from plan_manager.domain.bug_fix import (
    BUG_FIX_STATUSES, BUG_FIX_TYPES, validate_fix_status, validate_fix_type,
)
from plan_manager.domain.bug_impact import (
    BUG_IMPACT_STATUSES, BUG_IMPACT_TARGET_TYPES, BUG_IMPACT_TYPES,
    validate_impact_status, validate_impact_target_type, validate_impact_type,
)
from plan_manager.domain.comment_visibility import VISIBILITY_MODES, validate_visibility
from plan_manager.domain.execution_attempt import ATTEMPT_STATUSES, validate_attempt_status
from plan_manager.domain.model_binding import (
    BINDING_SCOPES, SPEC_LEVELS, InvalidBindingScopeError,
    validate_binding_scope, validate_scope_fields,
)
from plan_manager.domain.project_dependency import (
    DEPENDENCY_CONFIDENCES, DEPENDENCY_TYPES, DISCOVERY_SOURCES,
    guard_no_dependency_cycle, guard_no_duplicate_dependency,
    validate_confidence, validate_dependency_type, validate_discovery_source,
)
from plan_manager.domain.runtime_integrity import DuplicateLinkError, LinkCycleError
from plan_manager.domain.runtime_role import RUNTIME_ROLES, validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.todo_link import guard_no_blocking_cycle, guard_no_duplicate


def _domain_code(result) -> str:
    payload = result.to_dict()
    return payload["error"]["data"]["domain_code"]


def _assert_enumerates(validator, valid_values) -> str:
    with pytest.raises(RuntimeValidationError) as exc_info:
        validator("zz_not_a_real_value")
    message = str(exc_info.value)
    for value in sorted(valid_values):
        assert value in message
    return message


def test_project_already_bound_to_plan_code_retired() -> None:
    assert "PROJECT_ALREADY_BOUND_TO_PLAN" not in DOMAIN_CODES


def test_duplicate_link_code_reachable() -> None:
    candidate = (str(uuid.uuid4()), str(uuid.uuid4()), "blocks")
    existing = {candidate}
    with pytest.raises(DuplicateLinkError) as exc_info:
        guard_no_duplicate(existing, candidate)
    result = map_exception(exc_info.value)
    assert _domain_code(result) == "DUPLICATE_LINK"


def test_link_cycle_code_reachable() -> None:
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(LinkCycleError) as exc_info:
        guard_no_blocking_cycle([(a, b), (b, c), (c, a)])
    result = map_exception(exc_info.value)
    assert _domain_code(result) == "LINK_CYCLE"


def test_project_dependency_cycle_code_reachable_from_guard() -> None:
    a, b, c = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(DomainCommandError) as exc_info:
        guard_no_dependency_cycle([(a, b), (b, c), (c, a)])
    result = map_exception(exc_info.value)
    assert _domain_code(result) == "PROJECT_DEPENDENCY_CYCLE"


def test_duplicate_project_dependency_code_reachable_from_guard() -> None:
    candidate = (str(uuid.uuid4()), str(uuid.uuid4()), "library")
    existing = {candidate}
    with pytest.raises(DomainCommandError) as exc_info:
        guard_no_duplicate_dependency(existing, candidate)
    result = map_exception(exc_info.value)
    assert _domain_code(result) == "DUPLICATE_PROJECT_DEPENDENCY"


def test_bug_fix_type_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_fix_type, BUG_FIX_TYPES)


def test_bug_fix_status_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_fix_status, BUG_FIX_STATUSES)


def test_bug_impact_target_type_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_impact_target_type, BUG_IMPACT_TARGET_TYPES)


def test_bug_impact_type_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_impact_type, BUG_IMPACT_TYPES)


def test_bug_impact_status_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_impact_status, BUG_IMPACT_STATUSES)


def test_comment_visibility_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_visibility, VISIBILITY_MODES)


def test_binding_scope_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_binding_scope, BINDING_SCOPES)
    with pytest.raises(InvalidBindingScopeError) as exc_info:
        validate_scope_fields(
            "level",
            role=None,
            plan_uuid=uuid.uuid4(),
            spec_level="zz_not_a_real_value",
            branch_step_uuid=None,
            step_uuid=None,
        )
    message = str(exc_info.value)
    for level in sorted(SPEC_LEVELS):
        assert level in message


def test_runtime_role_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_runtime_role, RUNTIME_ROLES)


def test_dependency_type_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_dependency_type, DEPENDENCY_TYPES)


def test_discovery_source_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_discovery_source, DISCOVERY_SOURCES)


def test_dependency_confidence_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_confidence, DEPENDENCY_CONFIDENCES)


def test_execution_attempt_status_message_enumerates_valid_values() -> None:
    _assert_enumerates(validate_attempt_status, ATTEMPT_STATUSES)


def test_todo_link_add_documents_mapped_codes() -> None:
    error_cases = TodoLinkAddCommand.metadata()["error_cases"]
    assert "DUPLICATE_LINK" in error_cases
    assert "LINK_CYCLE" in error_cases
    rve_description = error_cases["RUNTIME_VALIDATION_ERROR"]["description"].lower()
    assert "duplicate" not in rve_description
    assert "cycle" not in rve_description


def test_project_dependency_add_documents_duplicate_code() -> None:
    best_practices = " ".join(ProjectDependencyAddCommand.metadata()["best_practices"])
    assert "DUPLICATE_ID" not in best_practices
    assert "DUPLICATE_PROJECT_DEPENDENCY" in best_practices


def test_model_binding_error_case_templates_match_runtime() -> None:
    assert "expected one of" in MODEL_ERROR_CASES["INVALID_BINDING_SCOPE"]["message"]
    assert "expected one of" in MODEL_ERROR_CASES["INVALID_RUNTIME_ROLE"]["message"]


def _command_class(name: str):
    module = import_module(f"plan_manager.commands.{name}_command")
    class_name = "".join(part.capitalize() for part in name.split("_")) + "Command"
    return getattr(module, class_name)


# allowlisted per L1 ruling 2026-07-16 — pre-existing out-of-scope surfaces;
# frozen A-014 authored pre-wave-2: export_upload_save documents the raw
# file-transfer-subsystem exception names it actually surfaces, and info uses
# the literal 'none' sentinel meaning "no domain error applies".
_ERROR_CASE_ALLOWLIST: dict[str, frozenset[str]] = {
    "export_upload_save": frozenset({
        "InvalidRequest",
        "TransferSessionNotFoundError",
        "TransferError",
        "TransferChecksumMismatchError",
    }),
    "info": frozenset({"none"}),
    "ops_status": frozenset({"none"}),
}


def test_every_documented_error_case_code_is_registered() -> None:
    unregistered: list[str] = []
    for name in INVENTORY:
        cls = _command_class(name)
        error_cases = cls.metadata().get("error_cases", {})
        for code in error_cases:
            if code in _ERROR_CASE_ALLOWLIST.get(name, frozenset()):
                continue
            if code not in DOMAIN_CODES:
                unregistered.append(f"{name}: {code}")
    assert not unregistered, f"undocumented domain codes: {unregistered}"
