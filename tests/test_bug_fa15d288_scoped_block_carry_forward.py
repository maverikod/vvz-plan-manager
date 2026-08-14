"""Regression tests for bug fa15d288: a scoped step write must not stale the
whole plan's context blocks.

Block currency is a revision-identity predicate -- every reader (block_list,
block_get, block_rebuild, has_current_common_block, the context gate) counts a
stored row as current only when its (revision_uuid, cascade_uuid) pair equals
the plan's working pair. Because every step mutation bumps that pair, one
step_update used to stale EVERY block of the plan, including the plan-level
block, sibling branches, and ancestors whose content the write provably cannot
touch: a common block's content is a pure function of the node's OWN step
fields plus plan material (concepts, HRS paragraphs, relations), none of which
a step write mutates.

The fix leaves all five readers untouched and instead re-tags, at write time,
every block the mutation cannot have changed from the old working pair onto
the freshly minted new one.

No real database: the carry-forward is one UPDATE statement, so these tests
pin the statement verbatim and evaluate its documented predicate over an
in-memory row list (the pattern of
tests/test_bug_33a10275_cascade_commit_block_promotion.py, extended so the
selection rule itself is asserted and not only the SQL text).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import step_update_command
from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.domain.step import Step
from plan_manager.storage import version_store
from plan_manager.views import context_blocks as context_blocks_mod
from plan_manager.views.context_blocks import (
    carry_forward_context_blocks,
    has_current_common_block,
)


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000fa")
OTHER_PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000fb")
OLD_HEAD = uuid.UUID("00000000-0000-0000-0000-000000000f01")
NEW_HEAD = uuid.UUID("00000000-0000-0000-0000-000000000f02")
OLD_TIP = uuid.UUID("00000000-0000-0000-0000-000000000f03")
NEW_TIP = uuid.UUID("00000000-0000-0000-0000-000000000f04")
CASCADE_UUID = uuid.UUID("00000000-0000-0000-0000-000000000f05")

CARRY_FORWARD_SQL = (
    "UPDATE context_block SET revision_uuid = %s, cascade_uuid = %s "
    "WHERE plan_uuid = %s "
    "AND revision_uuid IS NOT DISTINCT FROM %s "
    "AND cascade_uuid IS NOT DISTINCT FROM %s "
    "AND node_path != ALL(%s::text[]) "
    "AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(content) AS entry "
    "WHERE entry->>'type' = 'step_definition' AND entry->>'path' = ANY(%s::text[]))"
)


# --------------------------------------------------------------------- fakes


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


def _block(
    node_path: str,
    *,
    kind: str = "common",
    revision_uuid: uuid.UUID | None = OLD_HEAD,
    cascade_uuid: uuid.UUID | None = None,
    step_definition_of: str | None = None,
    plan_uuid: uuid.UUID = PLAN_UUID,
    child_level: int = 5,
) -> dict:
    """One stored context_block row, as the carry-forward UPDATE sees it."""
    content: list[dict] = [{"type": "authoring_template"}, {"type": "standards"}]
    if step_definition_of is not None:
        content.append({"type": "step_definition", "path": step_definition_of})
    return {
        "plan_uuid": plan_uuid,
        "revision_uuid": revision_uuid,
        "cascade_uuid": cascade_uuid,
        "node_path": node_path,
        "child_level": child_level,
        "kind": kind,
        "content": content,
    }


class _RowStore:
    """Evaluates the carry-forward UPDATE and the currency SELECT in Python.

    ``execute`` accepts exactly the two statements this module's code under
    test issues and refuses anything else, so a change to either statement
    surfaces here instead of silently passing.
    """

    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, sql, params):
        statement = " ".join(sql.split())
        self.statements.append(statement)
        if statement == CARRY_FORWARD_SQL:
            return self._carry_forward(params)
        if statement.startswith("SELECT 1 FROM context_block"):
            return self._has_current_common(params)
        raise AssertionError(f"unexpected statement: {statement}")

    def _carry_forward(self, params):
        to_rev, to_cascade, plan_uuid, from_rev, from_cascade, paths, paths_again = params
        assert paths == paths_again, "both %s placeholders take the same changed_paths"
        changed = set(paths)
        moved = 0
        for row in self.rows:
            if row["plan_uuid"] != plan_uuid:
                continue
            if row["revision_uuid"] != from_rev or row["cascade_uuid"] != from_cascade:
                continue
            if row["node_path"] in changed:
                continue
            if any(
                entry.get("type") == "step_definition" and entry.get("path") in changed
                for entry in row["content"]
            ):
                continue
            row["revision_uuid"] = to_rev
            row["cascade_uuid"] = to_cascade
            moved += 1
        return _Result(moved)

    def _has_current_common(self, params):
        plan_uuid, node_path, child_level, revision_uuid, cascade_uuid = params
        for row in self.rows:
            if (
                row["plan_uuid"] == plan_uuid
                and row["node_path"] == node_path
                and row["child_level"] == child_level
                and row["kind"] == "common"
                and row["revision_uuid"] == revision_uuid
                and row["cascade_uuid"] == cascade_uuid
            ):
                return _FetchOne((1,))
        return _FetchOne(None)


class _FetchOne:
    def __init__(self, row) -> None:
        self._row = row

    def fetchone(self):
        return self._row


def _tagged(store: _RowStore, node_path: str) -> tuple:
    row = next(row for row in store.rows if row["node_path"] == node_path)
    return (row["revision_uuid"], row["cascade_uuid"])


# ------------------------------------------------- (a) direct-mode head bump


def _direct_mode_rows() -> list[dict]:
    return [
        # Plan-level block: no step_definition at all, pure plan material.
        _block("plan", child_level=3),
        # The ancestor of the mutated step.
        _block("G-001", step_definition_of="G-001", child_level=4),
        # The mutated step's own block.
        _block("G-001/T-001", step_definition_of="G-001/T-001"),
        # A sibling branch, untouched by a write under G-001/T-001.
        _block("G-002/T-002", step_definition_of="G-002/T-002"),
    ]


def test_step_write_carries_plan_sibling_and_ancestor_blocks_to_the_new_head() -> None:
    store = _RowStore(_direct_mode_rows())

    carried = carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=NEW_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001"],
    )

    assert carried == 3
    assert store.statements == [CARRY_FORWARD_SQL]
    assert _tagged(store, "plan") == (NEW_HEAD, None)
    assert _tagged(store, "G-001") == (NEW_HEAD, None)
    assert _tagged(store, "G-002/T-002") == (NEW_HEAD, None)
    # The mutated step's own block is the one row whose content could have
    # changed, so it stays behind and correctly reads as stale.
    assert _tagged(store, "G-001/T-001") == (OLD_HEAD, None)


def test_carried_blocks_read_as_current_and_the_changed_step_block_does_not() -> None:
    store = _RowStore(_direct_mode_rows())
    carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=NEW_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001"],
    )

    # The reader is unchanged by this fix: it still compares the stored pair
    # with the plan's working pair, NULL-safely.
    assert has_current_common_block(store, PLAN_UUID, "plan", 3, NEW_HEAD, None) is True
    assert has_current_common_block(store, PLAN_UUID, "G-001", 4, NEW_HEAD, None) is True
    assert has_current_common_block(store, PLAN_UUID, "G-002/T-002", 5, NEW_HEAD, None) is True
    assert has_current_common_block(store, PLAN_UUID, "G-001/T-001", 5, NEW_HEAD, None) is False


def test_carry_forward_never_leaves_the_plan_or_the_old_pair() -> None:
    rows = _direct_mode_rows()
    rows.append(_block("plan", child_level=3, plan_uuid=OTHER_PLAN_UUID))
    # A block compiled against an older revision was already stale; it must
    # stay stale rather than be resurrected onto the new head.
    older = uuid.UUID("00000000-0000-0000-0000-000000000f00")
    rows.append(_block("G-003", step_definition_of="G-003", revision_uuid=older))
    store = _RowStore(rows)

    carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=NEW_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001"],
    )

    other_plan_row = next(row for row in store.rows if row["plan_uuid"] == OTHER_PLAN_UUID)
    assert (other_plan_row["revision_uuid"], other_plan_row["cascade_uuid"]) == (OLD_HEAD, None)
    assert _tagged(store, "G-003") == (older, None)


def test_carry_forward_is_a_noop_when_the_working_pair_did_not_move() -> None:
    store = _RowStore(_direct_mode_rows())

    carried = carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=OLD_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001"],
    )

    assert carried == 0
    assert store.statements == []


# ------------------------------------------------------- (b) compile rows


def test_compile_rows_are_excluded_by_their_recorded_step_definition_subject() -> None:
    """A compile row's subject step is recoverable from the stored row.

    ``compile_context`` writes the subject of its ``step_definition_of``
    include as a step_definition content entry carrying the canonical path
    (the same field ``_compile_include_from_record`` reads back). That makes
    the subject queryable in SQL, so compile rows need no blanket exclusion:
    only the ones whose subject is in the changed set stay behind.
    """
    store = _RowStore(
        [
            _block("plan", kind="compile", step_definition_of="G-001/T-001/A-001"),
            _block("plan", kind="compile", step_definition_of="G-002/T-002/A-002"),
            _block("plan", kind="compile", child_level=3),
        ]
    )

    carried = carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=NEW_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001/A-001"],
    )

    assert carried == 2
    subjects = {
        entry["path"]: (row["revision_uuid"], row["cascade_uuid"])
        for row in store.rows
        for entry in row["content"]
        if entry["type"] == "step_definition"
    }
    assert subjects["G-001/T-001/A-001"] == (OLD_HEAD, None)
    assert subjects["G-002/T-002/A-002"] == (NEW_HEAD, None)


def test_a_block_embedding_the_changed_step_stays_behind_even_at_another_node_path() -> None:
    store = _RowStore([_block("plan", kind="compile", step_definition_of="G-001/T-001")])

    carried = carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_HEAD,
        from_cascade=None,
        to_revision=NEW_HEAD,
        to_cascade=None,
        changed_paths=["G-001/T-001"],
    )

    assert carried == 0
    assert _tagged(store, "plan") == (OLD_HEAD, None)


# --------------------------------------------------------- (c) cascade tip


def test_cascade_tip_advance_carries_blocks_under_the_same_cascade() -> None:
    """Carried rows stay tip rows, so cascade_commit still promotes them.

    ``promote_cascade_blocks_to_head`` (bug 33a10275) promotes exactly the
    rows tagged (tip revision, cascade). Carrying a row forward writes the
    NEW tip with the SAME cascade, so it is a tip row by construction; rows
    left at an older cascade revision keep their tag and stay stale, which is
    the invariant bugs e3060750 and 33a10275 depend on.
    """
    store = _RowStore(
        [
            _block("plan", revision_uuid=OLD_TIP, cascade_uuid=CASCADE_UUID, child_level=3),
            _block(
                "G-001/T-001",
                revision_uuid=OLD_TIP,
                cascade_uuid=CASCADE_UUID,
                step_definition_of="G-001/T-001",
            ),
            # Compiled at the head before the cascade opened: not a tip row.
            _block("G-002", revision_uuid=OLD_HEAD, step_definition_of="G-002"),
        ]
    )

    carried = carry_forward_context_blocks(
        store,
        PLAN_UUID,
        from_revision=OLD_TIP,
        from_cascade=CASCADE_UUID,
        to_revision=NEW_TIP,
        to_cascade=CASCADE_UUID,
        changed_paths=["G-001/T-001"],
    )

    assert carried == 1
    assert _tagged(store, "plan") == (NEW_TIP, CASCADE_UUID)
    assert _tagged(store, "G-001/T-001") == (OLD_TIP, CASCADE_UUID)
    assert _tagged(store, "G-002") == (OLD_HEAD, None)


# ------------------------------------------- (d) opt-in only, at record_revision


def _patch_record_revision(monkeypatch, calls: dict) -> None:
    monkeypatch.setattr(
        version_store, "insert_node_version",
        lambda conn, plan_uuid, entity_uuid, content: uuid.uuid4(),
    )
    monkeypatch.setattr(
        version_store, "insert_revision",
        lambda conn, plan_uuid, parent, author, message, node_version_uuids: NEW_HEAD,
    )
    monkeypatch.setattr(
        version_store, "set_head_revision",
        lambda conn, plan_uuid, revision_uuid: calls.setdefault("head", revision_uuid),
    )
    def _carry(conn, plan_uuid, **kwargs):
        calls["carry"] = kwargs
        return 0

    # record_revision imports the helper lazily (import-cycle guard), so the
    # patch targets the owning views module.
    monkeypatch.setattr(context_blocks_mod, "carry_forward_context_blocks", _carry)


def test_record_revision_without_a_scope_keeps_global_invalidation(monkeypatch) -> None:
    calls: dict = {}
    _patch_record_revision(monkeypatch, calls)

    version_store.record_revision(
        object(), PLAN_UUID, "api", "paragraph edit", [], OLD_HEAD, None
    )

    assert calls["head"] == NEW_HEAD
    assert "carry" not in calls


def test_record_revision_with_a_scope_carries_from_the_parent_revision(monkeypatch) -> None:
    calls: dict = {}
    _patch_record_revision(monkeypatch, calls)

    version_store.record_revision(
        object(), PLAN_UUID, "api", "step_update: A-001", [], OLD_HEAD, None,
        carry_forward_paths=["G-001/T-001/A-001"],
    )

    assert calls["carry"] == {
        "from_revision": OLD_HEAD,
        "from_cascade": None,
        "to_revision": NEW_HEAD,
        "to_cascade": None,
        "changed_paths": ["G-001/T-001/A-001"],
    }


def test_record_revision_carries_across_a_cascade_tip_advance(monkeypatch) -> None:
    calls: dict = {}
    _patch_record_revision(monkeypatch, calls)

    class _Conn:
        def execute(self, sql, params):
            calls.setdefault("ref_update", params)

    version_store.record_revision(
        _Conn(), PLAN_UUID, "api", "step_update: A-001", [], OLD_TIP, "cascade/x",
        carry_forward_paths=["G-001/T-001/A-001"], cascade_uuid=CASCADE_UUID,
    )

    assert "head" not in calls
    assert calls["carry"] == {
        "from_revision": OLD_TIP,
        "from_cascade": CASCADE_UUID,
        "to_revision": NEW_HEAD,
        "to_cascade": CASCADE_UUID,
        "changed_paths": ["G-001/T-001/A-001"],
    }


# ------------------------------------------------ command wiring: step_update


_GS = uuid.UUID("00000000-0000-0000-0000-000000000011")
_TS = uuid.UUID("00000000-0000-0000-0000-000000000012")
_AS = uuid.UUID("00000000-0000-0000-0000-000000000013")


def _step(step_uuid, level, step_id, parent, fields=None) -> Step:
    return Step(
        uuid=step_uuid, plan_uuid=PLAN_UUID, parent_step_uuid=parent, level=level,
        step_id=step_id, slug=step_id.lower(), fields=fields or {}, depends_on=[],
        concepts=[], project_id=None, status="draft",
    )


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = OLD_HEAD
    completed = False


@contextmanager
def _fake_db():
    yield object()


def test_step_update_passes_the_mutated_step_path_as_the_carry_forward_scope(monkeypatch) -> None:
    atomic_fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1}
    nodes = {
        _GS: _step(_GS, 3, "G-001", None),
        _TS: _step(_TS, 4, "T-001", _GS),
        _AS: _step(_AS, 5, "A-001", _TS, atomic_fields),
    }
    calls: dict = {}

    monkeypatch.setattr(step_update_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_update_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_update_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(step_update_command, "list_concept_ids", lambda conn, plan_uuid: [])
    monkeypatch.setattr(step_update_command, "check_admission", lambda *a: None)
    monkeypatch.setattr(
        step_update_command, "update_step_fields_and_concepts",
        lambda conn, step_uuid, fields, concepts: nodes[step_uuid].fields.update(fields),
    )
    monkeypatch.setattr(step_update_command, "get_step", lambda conn, step_uuid: nodes[step_uuid])

    def _rev(conn, plan_uuid, actor, message, changes, parent, ref_name=None, **kwargs):
        calls["carry_forward_paths"] = kwargs.get("carry_forward_paths")
        return NEW_HEAD

    monkeypatch.setattr(step_update_command, "record_revision", _rev)

    result = asyncio.run(
        StepUpdateCommand().execute(plan="p", step_id="A-001", fields={"priority": 2})
    )

    assert result.to_dict()["success"] is True
    assert calls["carry_forward_paths"] == ["G-001/T-001/A-001"]
