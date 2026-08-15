"""Regression tests for EIG block A (todo 287bdfa6): an optional "role" key
on level-5 `fields.objects` declaration entries, plus the producer/consumer
views it feeds in `object_inventory`.

Acceptance pinned here:
1. a known-vocabulary role is accepted and normalized round-trip;
2. an absent role leaves normalize output byte-identical to the pre-role
   shape (legacy semantics fully unchanged);
3. an unknown/non-string role is rejected with the module's existing error
   style, exactly like every other objects[] shape problem;
4. `object_inventory` derives "producers", "consumers", and "roles" from
   role-carrying entries on a mixed plan;
5. a role-less plan's inventory keeps its pre-change existing keys
   byte-identical (regression pin) while gaining the three new, empty,
   additive keys;
6. legacy bare-string entries never carry a role (no interplay/crash).
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step_objects import (
    OBJECT_ROLES,
    normalize_as_object_declarations,
    validate_as_objects,
)
from plan_manager.views.objects import object_findings, object_inventory


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000287bdfa6")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _InventoryConn:
    def __init__(self, gs_rows, ts_rows, as_rows) -> None:
        self._gs_rows = gs_rows
        self._ts_rows = ts_rows
        self._as_rows = as_rows

    def execute(self, query: str, params=()):
        assert params == (PLAN_UUID,), params
        if "level = 3" in query:
            return _Rows(self._gs_rows)
        if "level = 4" in query:
            return _Rows(self._ts_rows)
        if "level = 5" in query:
            return _Rows(self._as_rows)
        raise AssertionError(query)


def test_role_accepted_and_normalized_round_trip():
    for role in OBJECT_ROLES:
        fields = {"objects": [{"name": "Widget", "concepts": ["C-001"], "role": role}]}
        normalized, problems = normalize_as_object_declarations(fields)
        assert problems == []
        assert normalized == [{"name": "Widget", "concepts": ["C-001"], "role": role}]
        assert validate_as_objects(fields) == []


def test_absent_role_is_byte_identical_to_legacy_shape():
    fields = {"objects": [{"name": "Widget", "concepts": ["C-001", "C-002"]}]}
    normalized, problems = normalize_as_object_declarations(fields)
    assert problems == []
    # Pre-role-support shape: exactly {"name": ..., "concepts": ...}, no
    # "role" key at all -- not "role": None.
    assert normalized == [{"name": "Widget", "concepts": ["C-001", "C-002"]}]
    assert list(normalized[0].keys()) == ["name", "concepts"]


def test_invalid_role_rejected_with_exact_error():
    fields = {"objects": [{"name": "Widget", "concepts": [], "role": "destroy"}]}
    normalized, problems = normalize_as_object_declarations(fields)
    assert normalized == []
    assert problems == [
        {
            "field_name": "objects",
            "index": 0,
            "message": (
                "objects[0].role must be one of: "
                "create, modify, consume, verify, document, package, deploy"
            ),
        }
    ]
    assert validate_as_objects(fields) == problems


def test_non_string_role_rejected():
    fields = {"objects": [{"name": "Widget", "concepts": [], "role": 7}]}
    problems = validate_as_objects(fields)
    assert problems == [
        {
            "field_name": "objects",
            "index": 0,
            "message": (
                "objects[0].role must be one of: "
                "create, modify, consume, verify, document, package, deploy"
            ),
        }
    ]


def test_legacy_bare_string_entries_never_carry_a_role():
    fields = {"objects": ["Widget"]}
    normalized, problems = normalize_as_object_declarations(
        fields, allow_legacy_strings=True
    )
    assert problems == []
    assert normalized == [{"name": "Widget", "concepts": []}]
    assert "role" not in normalized[0]
    # Strict (write-path) validation still rejects bare strings, unrelated
    # to role support.
    assert validate_as_objects(fields) == [
        {
            "field_name": "objects",
            "index": 0,
            "message": "objects[0] must be an object",
        }
    ]


def _step_row(target_file: str, objects: list) -> dict:
    return {"target_file": target_file, "objects": objects}


def test_object_inventory_producers_consumers_roles_on_mixed_plan():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as_creator = uuid.uuid4()
    as_consumer = uuid.uuid4()
    as_legacy = uuid.uuid4()

    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                _step_row(
                    "pkg/widget.py",
                    [{"name": "Widget", "concepts": ["C-001"], "role": "create"}],
                ),
                ["C-001"],
            ),
            (
                ts,
                "A-002",
                _step_row(
                    "pkg/consumer.py",
                    [{"name": "Widget", "concepts": [], "role": "consume"}],
                ),
                [],
            ),
            (
                ts,
                "A-003",
                _step_row(
                    "pkg/legacy.py",
                    [{"name": "Widget", "concepts": []}],
                ),
                [],
            ),
        ],
    )

    inventory = object_inventory(conn, PLAN_UUID)

    assert set(inventory) == {"Widget"}
    widget = inventory["Widget"]
    assert widget["producers"] == ["G-001/T-001/A-001"]
    assert widget["consumers"] == ["G-001/T-001/A-002"]
    assert widget["roles"] == {
        "G-001/T-001/A-001": "create",
        "G-001/T-001/A-002": "consume",
    }
    # The role-less declaring step (A-003) contributes to neither map.
    assert "G-001/T-001/A-003" not in widget["roles"]
    assert "G-001/T-001/A-003" not in widget["producers"]
    assert "G-001/T-001/A-003" not in widget["consumers"]
    # Existing keys are still populated from all three declaring steps.
    assert widget["artifact_paths"] == [
        "G-001/T-001/A-001",
        "G-001/T-001/A-002",
        "G-001/T-001/A-003",
    ]


def test_object_inventory_role_less_plan_existing_keys_byte_identical():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as_uuid = uuid.uuid4()

    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                _step_row("pkg/widget.py", [{"name": "Widget", "concepts": ["C-001"]}]),
                ["C-001"],
            ),
        ],
    )

    inventory = object_inventory(conn, PLAN_UUID)

    assert set(inventory) == {"Widget"}
    widget = inventory["Widget"]
    # Regression pin: these five keys and values are exactly what
    # object_inventory produced before role support existed.
    assert widget["owner_keys"] == [["pkg.widget", "G-001/T-001"]]
    assert widget["modules"] == ["pkg.widget"]
    assert widget["artifact_paths"] == ["G-001/T-001/A-001"]
    assert widget["declared_concepts"] == ["C-001"]
    assert widget["as_concepts"] == ["C-001"]
    # New keys are present but empty when no entry carries a role.
    assert widget["producers"] == []
    assert widget["consumers"] == []
    assert widget["roles"] == {}


# ---------------------------------------------------------------------------
# post-0.1.117 defect fix: consumer/reference roles must not trip legacy
# coverage.object_multiple_owner_keys / coverage.object_multiple_modules
# ownership-drift checks (block A / block-B collision, live evidence: a
# plan with A1 {Widget, role=create} target src/widget.py and A2 {Widget,
# role=consume} in a different module reds both checks even though A2 never
# claims ownership of Widget).
# ---------------------------------------------------------------------------


def test_create_and_consume_in_different_modules_yields_zero_ownership_findings():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as_create = uuid.uuid4()
    as_consume = uuid.uuid4()

    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                _step_row(
                    "src/widget.py",
                    [{"name": "Widget", "concepts": [], "role": "create"}],
                ),
                [],
            ),
            (
                ts,
                "A-002",
                _step_row(
                    "src/consumer.py",
                    [{"name": "Widget", "concepts": [], "role": "consume"}],
                ),
                [],
            ),
        ],
    )

    inventory = object_inventory(conn, PLAN_UUID)
    widget = inventory["Widget"]
    # Ownership is exclusively the create declaration: one owner key, one
    # module -- the consume declaration is a reference, not an ownership
    # claim.
    assert widget["owner_keys"] == [["src.widget", "G-001/T-001"]]
    assert widget["modules"] == ["src.widget"]
    # Producers/consumers/roles and artifact_paths stay fully populated.
    assert widget["producers"] == ["G-001/T-001/A-001"]
    assert widget["consumers"] == ["G-001/T-001/A-002"]
    assert widget["roles"] == {
        "G-001/T-001/A-001": "create",
        "G-001/T-001/A-002": "consume",
    }
    assert widget["artifact_paths"] == ["G-001/T-001/A-001", "G-001/T-001/A-002"]

    findings = object_findings(inventory)
    assert [f for f in findings if f["check"].startswith("multiple_")] == []


def test_two_create_declarations_in_different_modules_still_flagged():
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as1 = uuid.uuid4()
    as2 = uuid.uuid4()

    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                _step_row(
                    "pkg/alpha.py",
                    [{"name": "Widget", "concepts": [], "role": "create"}],
                ),
                [],
            ),
            (
                ts,
                "A-002",
                _step_row(
                    "pkg/beta.py",
                    [{"name": "Widget", "concepts": [], "role": "modify"}],
                ),
                [],
            ),
        ],
    )

    inventory = object_inventory(conn, PLAN_UUID)
    widget = inventory["Widget"]
    assert widget["owner_keys"] == [
        ["pkg.alpha", "G-001/T-001"],
        ["pkg.beta", "G-001/T-001"],
    ]
    assert widget["modules"] == ["pkg.alpha", "pkg.beta"]

    findings = object_findings(inventory)
    checks = {f["check"] for f in findings}
    assert "multiple_owner_keys" in checks
    assert "multiple_modules" in checks


def test_reference_roles_excluded_from_ownership_but_kept_elsewhere():
    """document/package/deploy declarations are references, not ownership."""
    gs = uuid.uuid4()
    ts = uuid.uuid4()
    as_create = uuid.uuid4()
    as_document = uuid.uuid4()
    as_package = uuid.uuid4()
    as_deploy = uuid.uuid4()

    conn = _InventoryConn(
        gs_rows=[(gs, "G-001")],
        ts_rows=[(ts, gs, "T-001")],
        as_rows=[
            (
                ts,
                "A-001",
                _step_row(
                    "src/widget.py",
                    [{"name": "Widget", "concepts": [], "role": "create"}],
                ),
                [],
            ),
            (
                ts,
                "A-002",
                _step_row(
                    "docs/widget.md",
                    [{"name": "Widget", "concepts": [], "role": "document"}],
                ),
                [],
            ),
            (
                ts,
                "A-003",
                _step_row(
                    "pkg/widget_pkg.py",
                    [{"name": "Widget", "concepts": [], "role": "package"}],
                ),
                [],
            ),
            (
                ts,
                "A-004",
                _step_row(
                    "deploy/widget.yaml",
                    [{"name": "Widget", "concepts": [], "role": "deploy"}],
                ),
                [],
            ),
        ],
    )

    inventory = object_inventory(conn, PLAN_UUID)
    widget = inventory["Widget"]
    assert widget["owner_keys"] == [["src.widget", "G-001/T-001"]]
    assert widget["modules"] == ["src.widget"]
    assert widget["roles"] == {
        "G-001/T-001/A-001": "create",
        "G-001/T-001/A-002": "document",
        "G-001/T-001/A-003": "package",
        "G-001/T-001/A-004": "deploy",
    }
    assert widget["artifact_paths"] == [
        "G-001/T-001/A-001",
        "G-001/T-001/A-002",
        "G-001/T-001/A-003",
        "G-001/T-001/A-004",
    ]

    findings = object_findings(inventory)
    assert [f for f in findings if f["check"].startswith("multiple_")] == []
