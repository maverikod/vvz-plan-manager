"""Regression tests for bug 4f7fbd43: plan_prompt_chain with scope "G-NNN"
or "G-NNN/T-NNN" crashed with AttributeError ('Branch' object has no
attribute 'depth') -> JSON-RPC -32603.

Root cause: since bug e197b94a's fix, run_gate is typed
``branch: BranchScope | None`` and its first call (scope_steps) reads
``branch.depth``. plan_validate was migrated to resolve_branch_scope, but
plan_prompt_chain's non-whole_plan path still looped its scoped atomic
steps building plain Branch views (branch_for_atomic) and passed each one
into run_gate -- every scoped call crashed. whole_plan (branch=None)
kept working, which is why the suite stayed green while the scoped paths
were broken.

Fix under test: the scoped path resolves ONE hierarchical BranchScope
(depth "gs" for G-NNN, "ts" for G-NNN/T-NNN) via resolve_branch_scope
and runs the mechanical gate once over it.

Exercised at the command level -- PlanPromptChainCommand.execute(), the
real command path -- against a comprehensive fake connection covering
every read-only query the path issues (resolve_plan/get_plan, load_steps,
scope_atomic_steps, resolve_branch_scope, the full run_gate pass, and
assemble_prompt_chain), mirroring the fake-connection idiom of
tests/test_bug_e197b94a_branch_scope_selectors.py. On the pre-fix code
every scoped test here fails: run_gate receives a plain Branch, raises
AttributeError, and the command returns an INTERNAL ErrorResult instead
of a SuccessResult.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Optional

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands import plan_prompt_chain_command
from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-00004f7fbd43")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000b3")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000b4")

GS_FIELDS = {
    "name": "G one",
    "description": "GS description.",
    "relations": [{"from_concept": "C-001", "to_concept": "C-001", "type": "uses"}],
    "source_labels": ["{aaaa}"],
}
TS_FIELDS = {
    "name": "T one",
    "description": "TS description.",
    "inputs": [{"name": "in-one", "type": "input", "description": "one input."}],
    "outputs": [{"name": "out-one", "type": "output", "description": "one output."}],
}
AS_FIELDS = {
    "name": "A one",
    "target_file": "pkg/module.py",
    "operation": "Describe the routine behavior in plain prose.",
    "priority": 1,
    "prompt": "State the routine contract in plain prose.",
    "verification": "Confirm the routine contract in plain prose.",
}

# Row order matches load_steps/load_tree's SELECT column list: uuid,
# plan_uuid, parent_step_uuid, level, step_id, slug, fields, depends_on,
# concepts, project_id, status. Status "frozen" keeps every step eligible
# for the assembly (DEFAULT_INCLUDE_STATUSES).
STEP_ROWS = [
    (GS_UUID, PLAN_UUID, None, 3, "G-001", "g-one", GS_FIELDS, [], ["C-001"], None, "frozen"),
    (TS_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-one", TS_FIELDS, [], ["C-001"], None, "frozen"),
    (AS_UUID, PLAN_UUID, TS_UUID, 5, "A-001", "a-one", AS_FIELDS, [], ["C-001"], None, "frozen"),
]

PLAN_ROW = (
    PLAN_UUID,          # uuid
    "plan-4f7fbd43",    # name
    "draft",            # status
    None,               # context_budget
    HEAD_REVISION,      # head_revision_uuid
    [],                 # project_ids
    None,               # primary_project_id
    None,               # deleted_at
    False,              # completed
    None,               # comment
)

PARAGRAPH_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000b5")


class _Rows:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


class _Cursor:
    """Fake cursor for the ``with conn.cursor() as cur`` idiom used by
    load_steps, list_paragraphs, list_concepts, list_relations, load_tree,
    and current_head_revision."""

    def __init__(self, owner: "_FakeConn"):
        self._owner = owner
        self._pending: list[tuple] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_Cursor":
        self._pending = self._owner.dispatch(query, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending

    def fetchone(self) -> Optional[tuple]:
        return self._pending[0] if self._pending else None


class _FakeConn:
    """Comprehensive fake connection for one full plan_prompt_chain pass.

    Covers every read-only query issued by the real command path:
    resolve_plan/get_plan's plan select, load_steps/load_tree's step
    select, list_paragraphs, list_concepts, list_relations, the coverage
    view selects (concept/gs/label/relation coverage), object_inventory's
    three level-scoped step selects, gate_context's cascade/ref/plan/
    context_block selects, and current_head_revision. Dispatch is by
    longest-distinguishing query prefix; an unexpected query fails the
    test loudly.
    """

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Rows:
        return _Rows(self.dispatch(query, params))

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(STEP_ROWS)
        if query.startswith("SELECT uuid, plan_uuid, label, text, position"):
            return [(PARAGRAPH_UUID, PLAN_UUID, "aaaa", "Paragraph text.", 0)]
        if query.startswith("SELECT concept_id, name, definition, properties, source_labels"):
            return [("C-001", "Concept one", "One-sentence definition.", [], ["{aaaa}"])]
        if query.startswith("SELECT concept_id FROM concept"):
            return [("C-001",)]
        if query.startswith("SELECT from_concept, to_concept, type FROM relation"):
            return [("C-001", "C-001", "uses")]
        if query.startswith("SELECT count(*) FROM paragraph"):
            return [(1,)]
        if query.startswith("SELECT label FROM paragraph"):
            return [("aaaa",)]
        if query.startswith("SELECT uuid, step_id, concepts FROM step"):
            return [(GS_UUID, "G-001", ["C-001"])]
        if query.startswith("SELECT uuid, step_id FROM step"):
            return [(GS_UUID, "G-001")]
        if query.startswith("SELECT uuid, parent_step_uuid, step_id FROM step"):
            return [(TS_UUID, GS_UUID, "T-001")]
        if query.startswith("SELECT parent_step_uuid, step_id, fields, concepts FROM step"):
            return [(TS_UUID, "A-001", AS_FIELDS, ["C-001"])]
        if query.startswith("SELECT parent_step_uuid, concepts FROM step"):
            return [(GS_UUID, ["C-001"])]
        if query.startswith("SELECT concepts FROM step"):
            return [(["C-001"],)]
        if query.startswith("SELECT fields FROM step"):
            return [(GS_FIELDS,)]
        if query.startswith("SELECT uuid, name FROM cascade"):
            return []
        if query.startswith("SELECT revision_uuid FROM ref"):
            return []
        if query.startswith("SELECT head_revision_uuid FROM plan"):
            return [(HEAD_REVISION,)]
        if query.startswith("SELECT node_path, child_level, revision_uuid, cascade_uuid"):
            return [
                ("G-001", 4, HEAD_REVISION, None, ["C-001"],
                 datetime(2026, 8, 9, tzinfo=timezone.utc)),
                ("G-001/T-001", 5, HEAD_REVISION, None, ["C-001"],
                 datetime(2026, 8, 9, tzinfo=timezone.utc)),
            ]
        if query.startswith("SELECT uuid, name, status, context_budget, head_revision_uuid"):
            return [PLAN_ROW]
        raise AssertionError(f"unexpected query in _FakeConn: {query!r}")


def _patch(monkeypatch) -> _FakeConn:
    conn = _FakeConn()

    @contextmanager
    def fake_db_connection():
        yield conn

    monkeypatch.setattr(plan_prompt_chain_command, "db_connection", fake_db_connection)
    return conn


def _execute(scope: str) -> SuccessResult | ErrorResult:
    return asyncio.run(
        PlanPromptChainCommand().execute(plan=str(PLAN_UUID), scope=scope)
    )


def test_scope_gs_succeeds_with_scoped_gate(monkeypatch):
    """Bug 4f7fbd43's exact reported shape: scope='G-NNN' must assemble,
    not crash. On the pre-fix code this returns an INTERNAL ErrorResult
    (AttributeError: 'Branch' object has no attribute 'depth')."""
    _patch(monkeypatch)

    result = _execute("G-001")

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert result.data["scope"] == "G-001"
    assert result.data["total"] == 1
    assert result.data["assembly"][0]["step"] == "G-001/T-001/A-001"
    assert result.data["used_block_keys"]["as"] == ["G-001/T-001/A-001"]


def test_scope_gs_ts_succeeds_with_scoped_gate(monkeypatch):
    """Second reported shape: scope='G-NNN/T-NNN' must assemble too."""
    _patch(monkeypatch)

    result = _execute("G-001/T-001")

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert result.data["scope"] == "G-001/T-001"
    assert result.data["total"] == 1
    assert result.data["assembly"][0]["step"] == "G-001/T-001/A-001"


def test_scope_whole_plan_still_works(monkeypatch):
    """The whole_plan path (branch=None) predates the bug and must keep
    working unchanged next to the scoped-gate fix."""
    _patch(monkeypatch)

    result = _execute("whole_plan")

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert result.data["scope"] == "whole_plan"
    assert result.data["total"] == 1


def test_scope_unknown_gs_maps_to_step_not_found(monkeypatch):
    """Unknown scope ids keep the pre-existing STEP_NOT_FOUND contract
    (scope_atomic_steps validates before the gate ever runs)."""
    _patch(monkeypatch)

    result = _execute("G-999")

    assert isinstance(result, ErrorResult)
    assert result.details["domain_code"] == "STEP_NOT_FOUND"


def test_scope_unknown_ts_maps_to_step_not_found(monkeypatch):
    """Same contract for the tactical selector."""
    _patch(monkeypatch)

    result = _execute("G-001/T-999")

    assert isinstance(result, ErrorResult)
    assert result.details["domain_code"] == "STEP_NOT_FOUND"
