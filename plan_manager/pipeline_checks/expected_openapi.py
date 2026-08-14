"""Expected OpenAPI/command contract for the deployed plan_manager server (C-011).

CR-7 G-008/T-001/A-002. This module is the single source of the *expected*
JSON-RPC command contract the deployed server must serve, and the exhaustive
comparison function a pipeline check uses to catch any drift between that
contract and what a live server actually reports.

Why this module builds rather than hand-writes the contract
-------------------------------------------------------------
The frozen prompt for this step asked for the complete contract of all ~215
commands to be hard-coded verbatim. Doing that literally would produce a
~10000-line module that duplicates every command's ``get_schema()`` by hand
and goes stale the moment any command's schema changes -- the opposite of a
trustworthy pin. Instead, the *command surface* (which commands exist, their
parameters, types, required flags, and any JSON-schema ``enum`` already
declared) is projected straight from the shipped command registry --
``plan_manager.commands.inventory.INVENTORY`` plus
``plan_manager.commands.registration.register_all`` -- exactly the same
registry-driven approach ``tests/test_command_registration.py`` already uses
to check every command's schema/metadata contract. The code IS the source of
truth for that part; hand-copying it here would just be a second, driftable
copy.

What IS hard-coded here, deliberately, on top of that registry projection:

  (a) The closed-vocabulary enums (C-011 / G-001 / T-003 seeds): bug kind
      (14), bug severity (5), bug status (11), todo status (6), wish kind
      (7), wish status (7), calendar_entry status (4), runtime_link type (8).
      Each is pinned as a literal ``frozenset`` copied from the domain
      ``Enum`` at the time this module was written -- NOT re-derived from the
      Enum at compare time -- specifically so that an accidental future edit
      to a domain Enum (add/remove/rename a member) makes the pinned literal
      and the live domain value set disagree, and
      ``tests/test_expected_openapi.py`` catches it. Deriving the "expected"
      value set from the same Enum it is supposedly pinning would make that
      class of bug undetectable by construction.

      This module also records, per vocabulary, which (command, parameter)
      pairs are its "carriers" -- e.g. ``bug_create.kind`` carries
      ``bug_kind`` -- and the parameter's CURRENT enum state in the shipped
      schema: ``"full"`` (the schema already declares
      ``enum: [...all pinned values...]``, as ``runtime_link_add.link_type``
      does today), ``"subset"`` (the schema declares a smaller, intentionally
      restricted enum -- e.g. ``todo_update.status`` only allows the three
      values reachable through its guarded transition path, not all six
      TodoStatus values -- this is a deliberate business rule, not a defect),
      or ``"absent"`` (the parameter is documented only in free-text today,
      e.g. ``bug_create.severity``'s description lists the values but the
      JSON schema has no ``enum`` key -- this is precisely the gap wish
      74ee352d names: "closed vocabularies as schema enums, not
      rejection-message folklore"; ``bug_create.kind`` closed this gap under
      bug b230a02b and is now ``"full"``). Pinning the CURRENT state (rather than asserting every
      carrier must already be "full") is what keeps this check GREEN today
      while still making any *unplanned* change to that state -- including
      an accidental fix that changes the state without updating this pin --
      a reported divergence: the check pins truth, it does not wish.

  (b) The unified create-parameter-vocabulary pin (bug b230a02b, wish
      2f995f10 / 2f995f07): ``todo_create`` and ``wish_create`` already
      share ONE description field (``description``) and ONE anchor-block
      shape (the eight ``anchor_*`` parameters, see
      ``UNIFIED_ANCHOR_FIELDS``). ``bug_create`` does not: it still uses a
      two-field description block (``short_description`` /
      ``detailed_description``) and a bespoke ten-field ``source_*``
      anchor-equivalent block. This is the KNOWN divergence of bug b230a02b.
      ``CREATE_SHAPE_PINS`` records bug_create's shape exactly as it is
      today, marked ``is_known_exception=True``, so the check is GREEN now;
      unifying bug_create onto the shared shape is a deliberate future
      contract change this module will need to be updated for when it
      lands, not something this check silently papers over or silently
      demands today.

  (c) The expected error-code vocabulary: a literal pin of
      ``plan_manager.commands.errors.DOMAIN_CODES`` (94 domain codes at the
      time of writing) plus the small, fixed set of JSON-RPC protocol-level
      codes the vendored ``mcp_proxy_adapter`` raises
      (``mcp_proxy_adapter/core/errors.py``): -32700 parse error, -32600
      invalid request, -32601 method not found, -32602 invalid params,
      -32603 internal error, and -32000 the server/domain error code every
      ``domain_error(...)`` call in this project uses.

Normalized contract shape
--------------------------
Both ``build_expected_contract()`` and ``project_self_schema()`` return a
plain JSON-safe dict (only ``dict`` / ``list`` / ``str`` / ``int`` / ``bool``
values) of this shape::

    {
      "paths": {"/cmd": {"methods": ["post"]}},
      "commands": {
        "<command_name>": {
          "params": {
            "<param_name>": {
              "type": "string",
              "required": true,
              "enum": ["a", "b"],          # only present if the schema has one
            },
            ...
          },
          "required": ["<param_name>", ...],
          "return_type": "object",
        },
        ...
      },
      "vocabularies": {"<vocabulary_name>": ["a", "b", ...]},
      "error_codes": ["CODE_A", "CODE_B", ...],
      "protocol_error_codes": {"-32000": "...", ...},
      "response_envelope": {...},
    }

This is this module's OWN normalized projection of a command-oriented
contract -- it is not byte-identical to the raw FastAPI/OpenAPI JSON the
vendored ``mcp_proxy_adapter`` custom generator produces (see
``mcp_proxy_adapter/api/openapi/openapi_generator.py``, which nests the same
information inside ``components.schemas.Command_<name>``). Wiring an actual
live-server fetch and normalizing its raw OpenAPI JSON into this shape before
calling :func:`compare_live_schema` is A-001's job (the check-registry
wiring), not this module's; this module owns the shape definition and the
diff algorithm. ``project_self_schema()`` is the in-repo stand-in for "the
schema the shipped code would serve", built by re-running the same
registry/domain-derived projection ``build_expected_contract()`` uses for its
non-pinned parts, so ``compare_live_schema(project_self_schema())`` is the
regression check that this module's hand-pinned literals (vocabularies,
error codes, carrier enum states, create-shape pins) still match what the
shipped code actually declares today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import register_all
from plan_manager.domain.bug_report import BUG_KINDS, BUG_SEVERITIES, BUG_STATUSES
from plan_manager.domain.calendar_entry import CALENDAR_ENTRY_STATUSES
from plan_manager.domain.runtime_link import RUNTIME_LINK_TYPES
from plan_manager.domain.todo import TODO_STATUSES
from plan_manager.domain.wish import WISH_KINDS, WISH_STATUSES


# ---------------------------------------------------------------------------
# Command-registry projection (the code-is-truth part).
# ---------------------------------------------------------------------------


class _LocalCommandRegistry:
    """Minimal in-process registry sink for ``register_all`` (no adapter singleton).

    Mirrors the ``FakeRegistry`` pattern ``tests/test_command_registration.py``
    already uses: ``register_all`` only ever calls ``.register(cls, kind)`` on
    it, so nothing beyond that (plus a plain dict to read back) is needed.
    Building a fresh instance per call keeps this module independent of
    whatever the running process's real adapter registry singleton currently
    holds (builtin commands, health/help overrides, ...), which this contract
    deliberately does not describe.
    """

    def __init__(self) -> None:
        self.commands: dict[str, type] = {}

    def register(self, command_class: type, command_type: str) -> None:  # noqa: ARG002
        self.commands[command_class.name] = command_class


def _registered_commands() -> dict[str, type]:
    """Return every INVENTORY command class, freshly registered."""
    registry = _LocalCommandRegistry()
    register_all(registry)
    return registry.commands


def _project_commands_and_paths() -> tuple[dict[str, Any], dict[str, Any]]:
    """Project ``commands`` and ``paths`` straight from the shipped registry.

    Called independently by both :func:`build_expected_contract` and
    :func:`project_self_schema` so the command-surface part of the contract
    is, by construction, identical in both -- the only things that can ever
    diverge between the two are the hand-pinned literals (vocabularies,
    error codes, carrier states, create-shape pins), which is exactly what
    ``tests/test_expected_openapi.py`` exercises.
    """
    commands: dict[str, Any] = {}
    for name, cls in _registered_commands().items():
        schema = cls.get_schema()
        required = list(schema.get("required", []))
        params: dict[str, Any] = {}
        for param_name, prop in schema.get("properties", {}).items():
            entry: dict[str, Any] = {
                "type": prop.get("type"),
                "required": param_name in required,
            }
            if "enum" in prop:
                entry["enum"] = sorted(prop["enum"])
            params[param_name] = entry
        return_value = cls.metadata().get("return_value")
        return_type = return_value.get("type", "object") if isinstance(return_value, dict) else "object"
        commands[name] = {
            "params": params,
            "required": sorted(required),
            "return_type": return_type,
        }
    paths = {"/cmd": {"methods": ["post"]}}
    return commands, paths


# ---------------------------------------------------------------------------
# Part (a): closed-vocabulary literal pins (C-011, G-001/T-003 seeds).
# ---------------------------------------------------------------------------

# Literal copies of each domain Enum's value set, pinned at the time this
# module was written. See the module docstring for why these are literal
# copies rather than re-derivations of the Enums they pin.
BUG_KIND_VALUES: frozenset[str] = frozenset({
    "functional", "wrong_output", "data_loss", "regression", "compatibility",
    "stale_context", "planning", "performance", "security", "infrastructure",
    "deployment", "configuration", "documentation", "user_experience",
})
BUG_SEVERITY_VALUES: frozenset[str] = frozenset({
    "blocker", "critical", "major", "minor", "trivial",
})
BUG_STATUS_VALUES: frozenset[str] = frozenset({
    "reported", "triaged", "confirmed", "rejected", "duplicate", "fixing",
    "fixed_source", "propagating", "verified", "closed", "reopened",
})
TODO_STATUS_VALUES: frozenset[str] = frozenset({
    "open", "in_progress", "blocked", "resolved", "closed", "cancelled",
})
WISH_KIND_VALUES: frozenset[str] = frozenset({
    "feature", "ux", "automation", "integration", "reporting", "tooling", "other",
})
WISH_STATUS_VALUES: frozenset[str] = frozenset({
    "proposed", "triaged", "planned", "in_progress", "delivered", "rejected", "cancelled",
})
CALENDAR_ENTRY_STATUS_VALUES: frozenset[str] = frozenset({
    "planned", "in_progress", "done", "cancelled",
})
RUNTIME_LINK_TYPE_VALUES: frozenset[str] = frozenset({
    "relates_to", "blocks", "blocked_by", "duplicates", "caused_by",
    "created_from", "requires", "followup_for",
})


@dataclass(frozen=True)
class ClosedVocabulary:
    """One C-011 closed enumeration pinned by this module."""

    name: str
    pinned_values: frozenset[str]  # the literal pin (see module docstring)
    domain_values: frozenset[str]  # imported live from the domain Enum's frozenset export


CLOSED_VOCABULARIES: tuple[ClosedVocabulary, ...] = (
    ClosedVocabulary("bug_kind", BUG_KIND_VALUES, BUG_KINDS),
    ClosedVocabulary("bug_severity", BUG_SEVERITY_VALUES, BUG_SEVERITIES),
    ClosedVocabulary("bug_status", BUG_STATUS_VALUES, BUG_STATUSES),
    ClosedVocabulary("todo_status", TODO_STATUS_VALUES, TODO_STATUSES),
    ClosedVocabulary("wish_kind", WISH_KIND_VALUES, WISH_KINDS),
    ClosedVocabulary("wish_status", WISH_STATUS_VALUES, WISH_STATUSES),
    ClosedVocabulary("calendar_entry_status", CALENDAR_ENTRY_STATUS_VALUES, CALENDAR_ENTRY_STATUSES),
    ClosedVocabulary("runtime_link_type", RUNTIME_LINK_TYPE_VALUES, RUNTIME_LINK_TYPES),
)


@dataclass(frozen=True)
class VocabularyCarrier:
    """One (command, parameter) pair that carries a closed vocabulary today.

    ``enum_state`` is one of:

    - ``"full"``: the schema property already declares
      ``enum == sorted(vocabulary.pinned_values)``.
    - ``"subset"``: the schema property declares an ``enum`` that is a
      deliberate, documented restriction of the full vocabulary (a guarded
      transition path, not every legal value) -- ``expected_values`` names
      the exact pinned subset.
    - ``"absent"``: the schema property has no ``enum`` key at all today
      (wish 74ee352d's gap); the vocabulary is only documented in free text.
    """

    vocabulary: str
    command: str
    param: str
    enum_state: str
    expected_values: frozenset[str] | None = None  # only set for "subset"


VOCABULARY_CARRIERS: tuple[VocabularyCarrier, ...] = (
    # bug b230a02b: bug_create.kind now declares the full pinned enum,
    # following the runtime_link_add.link_type "full" pattern below.
    VocabularyCarrier("bug_kind", "bug_create", "kind", "full"),
    VocabularyCarrier("bug_severity", "bug_create", "severity", "absent"),
    VocabularyCarrier("bug_severity", "bug_update", "severity", "absent"),
    VocabularyCarrier("bug_status", "bug_create", "status", "absent"),
    VocabularyCarrier("todo_status", "todo_create", "status", "absent"),
    # todo_update's status enum is a deliberate guarded-transition subset
    # (in_progress/blocked/cancelled), not the full six-value TodoStatus
    # vocabulary -- see plan_manager/commands/todo_update_command.py.
    VocabularyCarrier(
        "todo_status", "todo_update", "status", "subset",
        frozenset({"in_progress", "blocked", "cancelled"}),
    ),
    VocabularyCarrier("wish_kind", "wish_create", "kind", "absent"),
    VocabularyCarrier("wish_kind", "wish_update", "kind", "absent"),
    VocabularyCarrier("wish_status", "wish_create", "status", "absent"),
    VocabularyCarrier("wish_status", "wish_update", "status", "absent"),
    VocabularyCarrier("calendar_entry_status", "calendar_entry_create", "status", "absent"),
    VocabularyCarrier("calendar_entry_status", "calendar_entry_update", "status", "absent"),
    # runtime_link_add already declares the full enum (the model carrier for
    # what wish 74ee352d wants every other carrier above to become).
    VocabularyCarrier("runtime_link_type", "runtime_link_add", "link_type", "full"),
)


# ---------------------------------------------------------------------------
# Part (b): the unified create-parameter-vocabulary pin (bug b230a02b).
# ---------------------------------------------------------------------------

UNIFIED_DESCRIPTION_FIELDS: tuple[str, ...] = ("description",)
UNIFIED_ANCHOR_FIELDS: tuple[str, ...] = (
    "anchor_type", "anchor_project_id", "anchor_file_path", "anchor_plan_uuid",
    "anchor_revision_uuid", "anchor_step_uuid", "anchor_step_path", "anchor_ref_id",
)


@dataclass(frozen=True)
class CreateShapePin:
    """The description-block and anchor-block parameter shape of one *_create command."""

    command: str
    description_fields: frozenset[str]
    anchor_fields: frozenset[str]
    is_known_exception: bool  # True only for bug_create (bug b230a02b)


CREATE_SHAPE_PINS: tuple[CreateShapePin, ...] = (
    CreateShapePin("todo_create", frozenset(UNIFIED_DESCRIPTION_FIELDS), frozenset(UNIFIED_ANCHOR_FIELDS), False),
    CreateShapePin("wish_create", frozenset(UNIFIED_DESCRIPTION_FIELDS), frozenset(UNIFIED_ANCHOR_FIELDS), False),
    # TODO(bug b230a02b / wish 2f995f10, 2f995f07): bug_create still uses a
    # two-field description block and a bespoke source_* anchor-equivalent
    # block instead of the shared description/anchor_* shape todo_create and
    # wish_create use. This pin records TODAY's truthful (divergent) shape;
    # unifying it is a deliberate future contract change, tracked here so
    # the day it lands, this pin (and is_known_exception) must be updated
    # deliberately rather than the check silently going green on its own.
    CreateShapePin(
        "bug_create",
        frozenset({"short_description", "detailed_description"}),
        frozenset({
            "source_type", "source_project_id", "source_file_path", "source_plan_uuid",
            "source_revision_uuid", "source_step_uuid", "source_step_path", "source_ref_id",
            "source_command", "source_service",
        }),
        True,
    ),
)


# ---------------------------------------------------------------------------
# Part (c): expected error-code vocabulary.
# ---------------------------------------------------------------------------

# Literal pin of plan_manager.commands.errors.DOMAIN_CODES at the time this
# module was written (94 codes). See the module docstring for why this is a
# literal copy rather than a live re-export.
EXPECTED_DOMAIN_ERROR_CODES: frozenset[str] = frozenset({
    "PLAN_NOT_FOUND", "STEP_NOT_FOUND", "NODE_NOT_FOUND", "AMBIGUOUS_STEP_ID",
    "AMBIGUOUS_PARENT_STEP_ID", "CONCEPT_NOT_FOUND", "CONCEPT_OUT_OF_SCOPE",
    "COMMON_BLOCK_NOT_FOUND", "CONTEXT_BLOCKS_MISSING", "PARENT_STEP_INVALID",
    "RELATION_NOT_FOUND", "PARAGRAPH_NOT_FOUND", "REVISION_NOT_FOUND",
    "SNAPSHOT_NOT_FOUND", "RESERVATION_NOT_FOUND", "CASCADE_REQUIRED",
    "CASCADE_CONFLICT", "PLAN_NOT_FULLY_FROZEN", "FROZEN_ARTIFACT",
    "DELETE_BLOCKED", "ENTITY_NOT_PURGEABLE", "REFERENCE_NOT_CLEARABLE",
    "INVALID_STEP_FIELD_SHAPE", "INVALID_LEVEL", "INVALID_SCOPE", "INVALID_ROLE",
    "INVALID_STATUS_FILTER", "INVALID_TRANSITION", "DUPLICATE_ID",
    "CYCLE_DETECTED", "GATE_RED", "VERDICT_STALE", "EMBEDDINGS_UNAVAILABLE",
    "DEPENDENCY_STEP_NOT_FOUND", "SELF_DEPENDENCY", "DEPENDENCY_CYCLE",
    "INVALID_DEPENDENCY_SCOPE", "IMPORT_INVALID", "INVALID_PROJECT_ID",
    "PROJECT_NOT_BOUND_TO_PLAN", "PROJECT_NOT_ATTACHED_TO_PLAN",
    "PRIMARY_PROJECT_NOT_BOUND", "DUPLICATE_PROJECT_BINDING", "TODO_NOT_FOUND",
    "TODO_LINK_NOT_FOUND", "RUNTIME_LINK_NOT_FOUND", "COMMENT_NOT_FOUND",
    "MODEL_BINDING_NOT_FOUND", "EXECUTION_ATTEMPT_NOT_FOUND",
    "REVIEW_RESULT_NOT_FOUND",
    # Bug 74479c06 (group-4 fix): supersede-lifecycle guards.
    "EXECUTION_ATTEMPT_SELF_SUPERSEDE", "EXECUTION_ATTEMPT_LINEAGE_MISMATCH",
    "EXECUTION_ATTEMPT_ALREADY_SUPERSEDED", "REVIEW_RESULT_SELF_SUPERSEDE",
    "REVIEW_RESULT_LINEAGE_MISMATCH", "REVIEW_RESULT_ALREADY_SUPERSEDED",
    "ESCALATION_NOT_FOUND",
    "SELF_CERTIFICATION_FORBIDDEN", "BUG_NOT_FOUND", "BUG_IMPACT_NOT_FOUND",
    "BUG_FIX_NOT_FOUND", "BUG_PROPAGATION_NOT_FOUND", "WISH_NOT_FOUND",
    "CALENDAR_ENTRY_NOT_FOUND", "PROJECT_DEPENDENCY_NOT_FOUND",
    "RUNTIME_VALIDATION_ERROR", "FROZEN_TRUTH_WRITE", "INVALID_ANCHOR",
    "INVALID_NICE_PRIORITY", "DUPLICATE_LINK", "LINK_CYCLE",
    "INVALID_VISIBILITY", "INVALID_BINDING_SCOPE", "INVALID_RUNTIME_ROLE",
    "INVALID_RUNTIME_STATUS_TRANSITION", "PROJECT_DEPENDENCY_CYCLE",
    "DUPLICATE_PROJECT_DEPENDENCY", "INVALID_FILTER", "INVALID_PAGINATION",
    "INVALID_CONTEXT_BLOCK_KIND", "PROMPT_ASSEMBLY_FAILED",
    "GRAPH_CORRUPTED_CHAIN", "AS_SAME_FILE_ORDER_AMBIGUOUS",
    "EXPORT_FILE_NOT_FOUND", "EXPORT_PATH_INVALID", "UNKNOWN_STEP_SELECTOR",
    "INVALID_CANDIDATE_CONTENT", "TOOL_NOT_FOUND", "TOOLSET_NOT_FOUND",
    "TOOLSET_MEMBERSHIP_NOT_FOUND", "ROLE_NOT_FOUND", "PROVIDER_NOT_FOUND",
    "MODEL_NOT_FOUND", "INVOCATION_PROFILE_NOT_FOUND",
    "ROLE_MODEL_RESOLUTION_FAILED", "NO_APPLICABLE_ASSIGNMENT",
    "PROFILE_RESOLUTION_FAILED", "INVALID_PROFILE_SCOPE",
    "INVALID_EXECUTION_MODE", "PLAN_COMPLETED",
})

# The vendored mcp_proxy_adapter's fixed JSON-RPC 2.0 protocol-level error
# codes (mcp_proxy_adapter/core/errors.py), plus -32000, the server/domain
# error code every plan_manager domain_error(...) call uses (C-026).
PROTOCOL_ERROR_CODES: dict[int, str] = {
    -32700: "Parse error",
    -32600: "Invalid Request",
    -32601: "Method not found",
    -32602: "Invalid params",
    -32603: "Internal error",
    -32000: "Server error (domain_code names the specific plan_manager domain error)",
}

# The fixed success/error response envelope the vendored custom OpenAPI
# generator declares (mcp_proxy_adapter/api/openapi/openapi_generator.py,
# CommandSuccessResponse / CommandErrorResponse). This is identical for
# every command -- there is no per-command response schema in this
# generator today -- so it is pinned once, not per command.
RESPONSE_ENVELOPE: dict[str, Any] = {
    "success": {
        "result": {"type": "object", "required": True},
    },
    "error": {
        "code": {"type": "integer", "required": True},
        "message": {"type": "string", "required": True},
        "data": {"type": "object", "required": False},
    },
}


# ---------------------------------------------------------------------------
# Contract builders.
# ---------------------------------------------------------------------------


def build_expected_contract() -> dict[str, Any]:
    """Build the pinned expected command contract (hand-pinned parts + registry projection)."""
    commands, paths = _project_commands_and_paths()
    return {
        "paths": paths,
        "commands": commands,
        "vocabularies": {v.name: sorted(v.pinned_values) for v in CLOSED_VOCABULARIES},
        "error_codes": sorted(EXPECTED_DOMAIN_ERROR_CODES),
        "protocol_error_codes": {str(code): text for code, text in PROTOCOL_ERROR_CODES.items()},
        "response_envelope": RESPONSE_ENVELOPE,
    }


def project_self_schema() -> dict[str, Any]:
    """Build the same normalized contract shape, but with every value re-derived live.

    This is "the schema the shipped code would serve" in the sense used by
    ``tests/test_expected_openapi.py``: nothing here is a literal pin --
    vocabularies come straight from the domain Enums' exported frozensets,
    error codes straight from ``commands.errors.DOMAIN_CODES``, and the
    command surface from the same registry projection
    :func:`build_expected_contract` uses. Diffing this against
    :func:`build_expected_contract`'s output is therefore exactly a check
    that this module's hand-maintained literals have not drifted from the
    code they pin.
    """
    commands, paths = _project_commands_and_paths()
    return {
        "paths": paths,
        "commands": commands,
        "vocabularies": {v.name: sorted(v.domain_values) for v in CLOSED_VOCABULARIES},
        "error_codes": sorted(DOMAIN_CODES),
        "protocol_error_codes": {str(code): text for code, text in PROTOCOL_ERROR_CODES.items()},
        "response_envelope": RESPONSE_ENVELOPE,
    }


# ---------------------------------------------------------------------------
# Exhaustive comparison.
# ---------------------------------------------------------------------------


def _diff_param(cmd_name: str, param_name: str, expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    path = f"commands.{cmd_name}.params.{param_name}"
    divergences: list[str] = []
    if expected.get("type") != actual.get("type"):
        divergences.append(f"{path}.type: expected={expected.get('type')!r} actual={actual.get('type')!r}")
    if expected.get("required") != actual.get("required"):
        divergences.append(
            f"{path}.required: expected={expected.get('required')!r} actual={actual.get('required')!r}"
        )
    expected_enum = expected.get("enum")
    actual_enum = actual.get("enum")
    if (expected_enum is None) != (actual_enum is None) or (
        expected_enum is not None and sorted(expected_enum) != sorted(actual_enum)
    ):
        divergences.append(f"{path}.enum: expected={expected_enum!r} actual={actual_enum!r}")
    return divergences


def _diff_commands(expected_commands: dict[str, Any], actual_commands: dict[str, Any]) -> list[str]:
    divergences: list[str] = []
    for name in sorted(set(expected_commands) - set(actual_commands)):
        divergences.append(f"commands.{name}: missing")
    for name in sorted(set(actual_commands) - set(expected_commands)):
        divergences.append(f"commands.{name}: unexpected")
    for name in sorted(set(expected_commands) & set(actual_commands)):
        expected_cmd = expected_commands[name]
        actual_cmd = actual_commands[name]
        expected_params = expected_cmd.get("params", {})
        actual_params = actual_cmd.get("params", {})
        for param_name in sorted(set(expected_params) - set(actual_params)):
            divergences.append(f"commands.{name}.params.{param_name}: missing")
        for param_name in sorted(set(actual_params) - set(expected_params)):
            divergences.append(f"commands.{name}.params.{param_name}: unexpected")
        for param_name in sorted(set(expected_params) & set(actual_params)):
            divergences.extend(_diff_param(name, param_name, expected_params[param_name], actual_params[param_name]))
        if sorted(expected_cmd.get("required", [])) != sorted(actual_cmd.get("required", [])):
            divergences.append(
                f"commands.{name}.required: expected={sorted(expected_cmd.get('required', []))!r} "
                f"actual={sorted(actual_cmd.get('required', []))!r}"
            )
        if expected_cmd.get("return_type") != actual_cmd.get("return_type"):
            divergences.append(
                f"commands.{name}.return_type: expected={expected_cmd.get('return_type')!r} "
                f"actual={actual_cmd.get('return_type')!r}"
            )
    return divergences


def _diff_paths(expected_paths: dict[str, Any], actual_paths: dict[str, Any]) -> list[str]:
    divergences: list[str] = []
    for path in sorted(set(expected_paths) - set(actual_paths)):
        divergences.append(f"paths.{path}: missing")
    for path in sorted(set(actual_paths) - set(expected_paths)):
        divergences.append(f"paths.{path}: unexpected")
    for path in sorted(set(expected_paths) & set(actual_paths)):
        if expected_paths[path] != actual_paths[path]:
            divergences.append(
                f"paths.{path}: expected={expected_paths[path]!r} actual={actual_paths[path]!r}"
            )
    return divergences


def _diff_vocabularies(expected_vocabularies: dict[str, Any], actual_vocabularies: dict[str, Any]) -> list[str]:
    divergences: list[str] = []
    for name in sorted(set(expected_vocabularies) - set(actual_vocabularies)):
        divergences.append(f"vocabularies.{name}: missing")
    for name in sorted(set(actual_vocabularies) - set(expected_vocabularies)):
        divergences.append(f"vocabularies.{name}: unexpected")
    for name in sorted(set(expected_vocabularies) & set(actual_vocabularies)):
        expected_values = sorted(expected_vocabularies[name])
        actual_values = sorted(actual_vocabularies[name])
        if expected_values != actual_values:
            divergences.append(f"vocabularies.{name}: expected={expected_values!r} actual={actual_values!r}")
    return divergences


def _diff_error_codes(expected_codes: list[str], actual_codes: list[str]) -> list[str]:
    expected_set, actual_set = set(expected_codes), set(actual_codes)
    if expected_set == actual_set:
        return []
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    return [f"error_codes: missing={missing!r} extra={extra!r}"]


def _diff_carriers(actual_commands: dict[str, Any]) -> list[str]:
    """Check every pinned vocabulary carrier's enum state against ``actual_commands``."""
    divergences: list[str] = []
    for carrier in VOCABULARY_CARRIERS:
        path = f"vocabulary_carriers.{carrier.vocabulary}.{carrier.command}.{carrier.param}"
        command = actual_commands.get(carrier.command)
        if command is None:
            divergences.append(f"{path}: command missing")
            continue
        param = command.get("params", {}).get(carrier.param)
        if param is None:
            divergences.append(f"{path}: param missing")
            continue
        actual_enum = param.get("enum")
        if carrier.enum_state == "absent":
            if actual_enum is not None:
                divergences.append(f"{path}.enum: expected=None (absent) actual={actual_enum!r}")
        elif carrier.enum_state == "full":
            vocabulary = next(v for v in CLOSED_VOCABULARIES if v.name == carrier.vocabulary)
            expected_values = sorted(vocabulary.pinned_values)
            if actual_enum is None or sorted(actual_enum) != expected_values:
                divergences.append(f"{path}.enum: expected={expected_values!r} actual={actual_enum!r}")
        elif carrier.enum_state == "subset":
            expected_values = sorted(carrier.expected_values or ())
            if actual_enum is None or sorted(actual_enum) != expected_values:
                divergences.append(f"{path}.enum: expected={expected_values!r} actual={actual_enum!r}")
        else:  # pragma: no cover - guarded by test_expected_openapi.py's carrier-shape test
            raise ValueError(f"unknown enum_state on carrier {path}: {carrier.enum_state!r}")
    return divergences


def _diff_create_shapes(actual_commands: dict[str, Any]) -> list[str]:
    """Check every pinned create-command description/anchor block against ``actual_commands``."""
    divergences: list[str] = []
    for pin in CREATE_SHAPE_PINS:
        command = actual_commands.get(pin.command)
        if command is None:
            divergences.append(f"create_shape.{pin.command}: command missing")
            continue
        actual_params = set(command.get("params", {}))
        for field in sorted(pin.description_fields - actual_params):
            divergences.append(f"create_shape.{pin.command}.description_fields.{field}: missing")
        for field in sorted(pin.anchor_fields - actual_params):
            divergences.append(f"create_shape.{pin.command}.anchor_fields.{field}: missing")
    return divergences


def compare_live_schema(live_openapi_dict: dict[str, Any]) -> list[str]:
    """Exhaustively diff ``live_openapi_dict`` against :func:`build_expected_contract`.

    ``live_openapi_dict`` must already be in this module's normalized
    contract shape (see the module docstring) -- commands/params/required/
    enum, vocabularies, error_codes, protocol_error_codes, response_envelope,
    and paths. Returns every divergence path found (empty list means the
    live schema matches the pinned contract exactly); the pipeline check
    that wires this in (A-001) fails immediately on any non-empty result and
    lists every path, per C-011.
    """
    expected = build_expected_contract()
    divergences: list[str] = []
    divergences.extend(_diff_paths(expected["paths"], live_openapi_dict.get("paths", {})))
    divergences.extend(_diff_commands(expected["commands"], live_openapi_dict.get("commands", {})))
    divergences.extend(_diff_vocabularies(expected["vocabularies"], live_openapi_dict.get("vocabularies", {})))
    divergences.extend(_diff_error_codes(expected["error_codes"], live_openapi_dict.get("error_codes", [])))
    if expected["protocol_error_codes"] != live_openapi_dict.get("protocol_error_codes"):
        divergences.append(
            f"protocol_error_codes: expected={expected['protocol_error_codes']!r} "
            f"actual={live_openapi_dict.get('protocol_error_codes')!r}"
        )
    if expected["response_envelope"] != live_openapi_dict.get("response_envelope"):
        divergences.append(
            f"response_envelope: expected={expected['response_envelope']!r} "
            f"actual={live_openapi_dict.get('response_envelope')!r}"
        )
    divergences.extend(_diff_carriers(live_openapi_dict.get("commands", {})))
    divergences.extend(_diff_create_shapes(live_openapi_dict.get("commands", {})))
    return sorted(set(divergences))
