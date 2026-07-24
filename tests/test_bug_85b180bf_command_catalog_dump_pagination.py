"""Regression tests for bug 85b180bf: command_catalog_dump(), called with no
params, previously returned the entire ~200+ command catalog (~130 KB) in a
single response instead of a bounded first page.

Fix (plan_manager.commands.command_catalog_dump_command.CommandCatalogDumpCommand):
apply the project's uniform limit/offset pagination contract
(plan_manager.commands.runtime_filtering: bounded default 50, max 200,
INVALID_PAGINATION on bad values) to the catalog entries, after sorting them
deterministically by command name (todo 9c409a47 -- INVENTORY order is
registration order, not a guaranteed-stable page boundary). The response
adds `returned`/`has_more` alongside the pre-existing `commands`/`total`/
`limit`/`offset` envelope keys (additive; existing keys/shape unchanged).

These tests exercise the command against a synthetic large catalog (via
monkeypatching build_command_catalog in the command module's namespace) so
the pagination/ordering contract is verified independent of however many
commands happen to be registered on any given day.
"""

from __future__ import annotations

import asyncio
import random

from plan_manager.commands import command_catalog_dump_command as ccd_module
from plan_manager.commands.command_catalog_dump_command import CommandCatalogDumpCommand
from plan_manager.commands.runtime_filtering import DEFAULT_LIMIT, MAX_LIMIT


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


def test_default_call_on_large_catalog_is_bounded_to_default_limit(monkeypatch):
    """The observed defect: command_catalog_dump() with no params must never
    dump the whole ~200+ command catalog (~130 KB) in one response."""
    _patch_catalog(monkeypatch, 222)

    result = _run()
    data = result.to_dict()["data"]

    assert len(data["commands"]) == DEFAULT_LIMIT == 50
    assert data["total"] == 222
    assert data["limit"] == DEFAULT_LIMIT
    assert data["offset"] == 0
    assert data["returned"] == 50
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
    """A catalog within the default page size (50) returns every command, and
    the only change vs. the pre-fix shape is the two new additive keys."""
    _patch_catalog(monkeypatch, 5, shuffled=False)

    result = _run()
    data = result.to_dict()["data"]

    assert set(data.keys()) == {"commands", "total", "limit", "offset", "returned", "has_more"}
    assert [entry["name"] for entry in data["commands"]] == [f"synthetic_cmd_{i:04d}" for i in range(5)]
    assert data["total"] == 5
    assert data["limit"] == 50
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


def test_default_schema_documents_limit_and_offset_with_canonical_pagination_contract():
    from plan_manager.commands.runtime_filtering import pagination_schema_properties

    properties = CommandCatalogDumpCommand.get_schema()["properties"]
    canonical = pagination_schema_properties()

    assert properties["limit"] == canonical["limit"]
    assert properties["offset"] == canonical["offset"]


def test_metadata_documents_returned_and_has_more_fields():
    blob = CommandCatalogDumpCommand.metadata()
    data_docs = blob["return_value"]["success"]["data"]

    assert "returned" in data_docs
    assert "has_more" in data_docs
    assert "total" in data_docs
    assert "limit" in data_docs
    assert "offset" in data_docs
