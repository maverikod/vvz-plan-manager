"""Regression tests for bug 85b180bf: command_catalog_dump(), called with no
params, previously returned the entire ~200+ command catalog (~130 KB) in a
single response instead of a bounded first page.

FIRST fix attempt (commit 8a3d6fc) bounded the default page to the shared
runtime_filtering.DEFAULT_LIMIT (50 entries) and sorted entries
deterministically by command name (todo 9c409a47) -- but count-only
bounding did NOT actually close the live defect. Acceptance-hold
investigation (same session, before this file's current form) proved it
empirically: unlike this project's other paginated entities (steps, bugs,
todos -- small structured records), each catalog entry embeds a COMPLETE
per-command metadata blob (full parameter descriptions/examples,
usage_examples, error_cases, best_practices); measured against the real,
live catalog (199 commands, 2026-07-24) entries average ~4.3 KB each (min
0.8 KB, max 9.7 KB), so a "bounded to 50 entries" page still serialized to
~248 KB -- almost DOUBLE the original bug's own ~130 KB complaint. See
plan_manager/commands/command_catalog_dump_command.py's module docstring
for the full measurement and the revised fix: this command's own no-param
default is `_DEFAULT_CATALOG_LIMIT` (10 entries, ~48 KB on the real
catalog), substituted BEFORE parse_pagination runs; parse_pagination's own
validation (1..MAX_LIMIT, INVALID_PAGINATION) and offset defaulting are
otherwise completely unchanged, and an explicitly-provided `limit` is never
overridden.

This file has two kinds of tests: (1) pagination/ordering-contract tests
against a synthetic large catalog (monkeypatching build_command_catalog),
verifying page-slicing math/ordering/no-dupes-no-gaps independent of
however many commands happen to be registered on any given day -- these
alone previously passed despite the real defect, because synthetic entries
were tiny; and (2) REAL-catalog byte-size regression tests (no
monkeypatching, exercising the actual build_command_catalog()) that would
have caught the true defect and are the ones that actually prove the fix.
"""

from __future__ import annotations

import asyncio
import json
import random

from plan_manager.commands import command_catalog_dump_command as ccd_module
from plan_manager.commands.command_catalog_dump_command import (
    _DEFAULT_CATALOG_LIMIT,
    CommandCatalogDumpCommand,
)
from plan_manager.commands.runtime_filtering import MAX_LIMIT


def _synthetic_entry(i: int) -> dict:
    return {
        "name": f"synthetic_cmd_{i:04d}",
        "category": "synthetic",
        "parameters": {},
        "execution_mode": "direct",
        "metadata": {
            "description": f"Synthetic catalog entry {i:04d}.",
            "error_cases": {},
            "best_practices": [],
            "usage_examples": [],
        },
        "source_module": f"plan_manager.commands.synthetic_cmd_{i:04d}_command",
    }


def _synthetic_catalog(n: int, shuffled: bool = True) -> list[dict]:
    entries = [_synthetic_entry(i) for i in range(n)]
    if shuffled:
        rng = random.Random(1234)
        rng.shuffle(entries)
    return entries


def _patch_catalog(monkeypatch, n: int, shuffled: bool = True) -> None:
    monkeypatch.setattr(ccd_module, "build_command_catalog", lambda: _synthetic_catalog(n, shuffled=shuffled))


def _run(**kwargs):
    return asyncio.run(CommandCatalogDumpCommand().execute(**kwargs))


# --- real-catalog byte-size regression (the tests that actually prove the fix) ---


def test_real_default_no_arg_response_is_bounded_to_the_catalog_specific_default():
    """No monkeypatching: exercises the ACTUAL live command inventory, exactly
    as a no-param JSON-RPC call would. This is the test that would have
    caught the original defect -- a page bounded to 50 *entries* still
    serialized to ~248 KB on the real catalog, because entries are large.
    """
    result = _run()
    data = result.to_dict()["data"]

    assert data["limit"] == _DEFAULT_CATALOG_LIMIT == 10
    assert len(data["commands"]) <= _DEFAULT_CATALOG_LIMIT
    assert data["returned"] == len(data["commands"])
    assert data["total"] >= 100  # sanity: real catalog is not accidentally empty/tiny


def test_real_default_no_arg_response_size_is_actually_bounded_in_bytes():
    """The defect's own terms: called with no params, the response body must
    stay well under the ~130 KB the bug complained about -- not just be
    bounded in entry *count*. Measured on the real catalog (2026-07-24): 10
    entries ~= 48 KB; this asserts a generous-but-real ceiling (80 KB) that
    catches both a reverted count-fix and a per-entry metadata bloat
    regression, without being so tight it flakes as the catalog grows by a
    handful of commands.
    """
    result = _run()
    payload = result.to_dict()

    size = len(json.dumps(payload))
    assert size < 80_000, f"default no-arg response is {size} bytes -- not actually bounded"


def test_real_explicit_max_limit_response_still_reflects_full_catalog_scope():
    """An explicit large limit (up to MAX_LIMIT) is still an informed,
    opt-in choice per the binding design decision ("full catalog remains
    reachable by paging ... do NOT add an unbounded escape hatch") -- it is
    the no-param DEFAULT that must be small, not the ceiling."""
    result = _run(limit=MAX_LIMIT)
    data = result.to_dict()["data"]

    assert data["limit"] == MAX_LIMIT == 200
    assert len(data["commands"]) == min(MAX_LIMIT, data["total"])


# --- pagination / ordering contract (synthetic catalog, size-independent) ---


def test_default_call_on_large_catalog_is_bounded_to_command_specific_default(monkeypatch):
    """The observed defect, restated in count terms: command_catalog_dump()
    with no params must never dump the whole catalog in one response."""
    _patch_catalog(monkeypatch, 222)

    result = _run()
    data = result.to_dict()["data"]

    assert len(data["commands"]) == _DEFAULT_CATALOG_LIMIT == 10
    assert data["total"] == 222
    assert data["limit"] == _DEFAULT_CATALOG_LIMIT
    assert data["offset"] == 0
    assert data["returned"] == 10
    assert data["has_more"] is True


def test_default_limit_never_exceeds_max_limit_even_if_requested(monkeypatch):
    _patch_catalog(monkeypatch, 500)

    result = _run(limit=MAX_LIMIT)
    data = result.to_dict()["data"]

    assert data["limit"] == MAX_LIMIT == 200
    assert len(data["commands"]) == MAX_LIMIT
    assert data["total"] == 500
    assert data["has_more"] is True


def test_small_catalog_returns_everything_with_additive_keys_only(monkeypatch):
    """A catalog within the command-specific default page size (10) returns
    every command, and the only change vs. the pre-fix shape is the two new
    additive keys."""
    _patch_catalog(monkeypatch, 5, shuffled=False)

    result = _run()
    data = result.to_dict()["data"]

    assert set(data.keys()) == {"commands", "total", "limit", "offset", "returned", "has_more"}
    assert [entry["name"] for entry in data["commands"]] == [f"synthetic_cmd_{i:04d}" for i in range(5)]
    assert data["total"] == 5
    assert data["limit"] == _DEFAULT_CATALOG_LIMIT
    assert data["offset"] == 0
    assert data["returned"] == 5
    assert data["has_more"] is False


def test_explicit_limit_and_offset_slice_the_sorted_catalog_with_correct_math(monkeypatch):
    _patch_catalog(monkeypatch, 10, shuffled=True)

    result = _run(limit=3, offset=4)
    data = result.to_dict()["data"]

    assert [entry["name"] for entry in data["commands"]] == [
        "synthetic_cmd_0004",
        "synthetic_cmd_0005",
        "synthetic_cmd_0006",
    ]
    assert data["total"] == 10
    assert data["limit"] == 3
    assert data["offset"] == 4
    assert data["returned"] == 3
    assert data["has_more"] is True


def test_last_page_returned_and_has_more_reflect_the_partial_tail(monkeypatch):
    _patch_catalog(monkeypatch, 205, shuffled=True)

    result = _run(limit=50, offset=200)
    data = result.to_dict()["data"]

    assert data["total"] == 205
    assert data["limit"] == 50
    assert data["offset"] == 200
    assert data["returned"] == 5
    assert len(data["commands"]) == 5
    assert data["has_more"] is False


def test_pagination_covers_every_entry_alphabetically_with_no_duplicates_or_gaps(monkeypatch):
    _patch_catalog(monkeypatch, 313, shuffled=True)

    seen: list[str] = []
    offset = 0
    while True:
        result = _run(limit=50, offset=offset)
        data = result.to_dict()["data"]
        seen.extend(entry["name"] for entry in data["commands"])
        if not data["has_more"]:
            break
        offset += data["limit"]

    expected = sorted(f"synthetic_cmd_{i:04d}" for i in range(313))
    assert seen == expected
    assert len(seen) == len(set(seen)) == 313


def test_pagination_covers_every_entry_using_the_no_arg_default_page_size(monkeypatch):
    """Same no-dupes/no-gaps walk as above, but paging with the OMITTED
    default (10) on every call after the first -- the actual shape a caller
    gets if it just keeps calling with offset=offset+returned and no
    explicit limit."""
    _patch_catalog(monkeypatch, 47, shuffled=True)

    seen: list[str] = []
    offset = 0
    while True:
        result = _run(offset=offset)
        data = result.to_dict()["data"]
        seen.extend(entry["name"] for entry in data["commands"])
        if not data["has_more"]:
            break
        offset += data["limit"]

    expected = sorted(f"synthetic_cmd_{i:04d}" for i in range(47))
    assert seen == expected
    assert len(seen) == len(set(seen)) == 47


def test_invalid_pagination_surfaces_invalid_pagination_domain_code(monkeypatch):
    _patch_catalog(monkeypatch, 5)

    result = _run(limit=0)
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_invalid_pagination_negative_offset_surfaces_invalid_pagination_domain_code(monkeypatch):
    _patch_catalog(monkeypatch, 5)

    result = _run(offset=-1)
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_invalid_pagination_limit_above_max_surfaces_invalid_pagination_domain_code(monkeypatch):
    _patch_catalog(monkeypatch, 5)

    result = _run(limit=MAX_LIMIT + 1)
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


# --- full dispatch-path regression: R24_limit_zero_invalid_pagination ---
#
# Every test above this point calls execute() directly (see `_run`), which
# bypasses validate_params() entirely. The REAL server dispatch path is
# mcp_proxy_adapter.commands.base.Command.run() -> validate_params() ->
# execute(): validate_params() runs a JSON-schema check
# (Command._validate_schema_value) BEFORE execute() is ever entered. Before
# this fix, the shared runtime_filtering.PAGINATION_FIELDS declared
# "minimum": 1 / "maximum": 200 on `limit` and "minimum": 0 on `offset`, so
# an explicit out-of-range value (limit=0, offset=-1) was rejected by
# validate_params() with a generic adapter ValidationError ("must be >= 1,
# got 0") -- execute() and parse_pagination()'s domain-level
# INVALID_PAGINATION were never reached at all. This is exactly what
# scripts/live_smoke.py's R24_limit_zero_invalid_pagination caught against
# the real deployed server (0.1.65): the string "INVALID_PAGINATION" never
# appeared in the error response. The tests below exercise validate_params()
# then execute() in sequence (the same two steps Command.run() performs;
# the registry-lookup step in between is orthogonal to this bug and is not
# needed to reproduce or prove it) and prove the domain code now surfaces
# correctly end-to-end.


def test_dispatch_path_limit_zero_surfaces_invalid_pagination_domain_code(monkeypatch):
    """R24 regression: limit=0 must reach parse_pagination() -- and thus
    INVALID_PAGINATION -- through the full validate_params() -> execute()
    path, not be shadowed by a JSON-schema "minimum" bound."""
    _patch_catalog(monkeypatch, 5)
    command = CommandCatalogDumpCommand()

    validated = command.validate_params({"limit": 0})  # must NOT raise post-fix
    result = asyncio.run(command.execute(**validated))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_dispatch_path_negative_offset_surfaces_invalid_pagination_domain_code(monkeypatch):
    """Symmetry with limit=0 above: offset=-1 must reach parse_pagination()
    through the full dispatch path too, not be shadowed by a JSON-schema
    "minimum": 0 bound on `offset`."""
    _patch_catalog(monkeypatch, 5)
    command = CommandCatalogDumpCommand()

    validated = command.validate_params({"offset": -1})  # must NOT raise post-fix
    result = asyncio.run(command.execute(**validated))
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "INVALID_PAGINATION"


def test_ordering_is_deterministic_across_two_consecutive_calls(monkeypatch):
    """todo 9c409a47: page boundaries must be stable across repeated calls --
    the catalog is re-fetched (and, per this fix, freshly re-sorted) on every
    call, so two consecutive calls with identical params must agree exactly,
    even though the underlying (synthetic) catalog order is shuffled."""
    _patch_catalog(monkeypatch, 137, shuffled=True)

    first = _run(limit=50, offset=40)
    second = _run(limit=50, offset=40)

    names_first = [entry["name"] for entry in first.to_dict()["data"]["commands"]]
    names_second = [entry["name"] for entry in second.to_dict()["data"]["commands"]]

    assert names_first == names_second
    assert names_first == sorted(names_first)


def test_schema_offset_matches_canonical_pagination_contract_limit_documents_true_default():
    """This command is NOT part of the byte-for-byte
    pagination_schema_properties() contract enforced by
    tests/test_uniform_pagination_contract.py's _RETROFITTED_COMMANDS list
    (by design -- see the command module's docstring): `offset` matches the
    canonical shared property exactly (its semantics/default are unchanged),
    but `limit`'s description is deliberately overridden to truthfully
    document the smaller, command-specific default (10, not the general
    50) -- type still matches the canonical contract. Neither the canonical
    fragment nor this command's own copy declares "minimum"/"maximum" (see
    runtime_filtering.PAGINATION_FIELDS' note, bug
    R24_limit_zero_invalid_pagination): range enforcement is
    parse_pagination()'s sole responsibility, never the JSON-schema layer."""
    from plan_manager.commands.runtime_filtering import pagination_schema_properties

    properties = CommandCatalogDumpCommand.get_schema()["properties"]
    canonical = pagination_schema_properties()

    assert properties["offset"] == canonical["offset"]

    limit_property = properties["limit"]
    assert limit_property["type"] == canonical["limit"]["type"]
    assert "minimum" not in limit_property
    assert "maximum" not in limit_property
    assert limit_property != canonical["limit"], "limit description must diverge to document the true default"
    assert str(_DEFAULT_CATALOG_LIMIT) in limit_property["description"]


def test_metadata_documents_returned_and_has_more_fields():
    blob = CommandCatalogDumpCommand.metadata()
    data_docs = blob["return_value"]["success"]["data"]

    assert "returned" in data_docs
    assert "has_more" in data_docs
    assert "total" in data_docs
    assert "limit" in data_docs
    assert "offset" in data_docs


def test_metadata_limit_parameter_documents_the_true_default_of_ten():
    blob = CommandCatalogDumpCommand.metadata()
    limit_doc = blob["parameters"]["limit"]["description"]

    assert "default 10" in limit_doc
    assert "default 50" not in limit_doc  # no stale claim from the first fix attempt
