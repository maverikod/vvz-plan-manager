# T-001 HRS Paragraph Access Context

Branch: `G-007/T-001`
Parent GS: `G-007-exchange-format`
Active plan root: `docs/plans/2026-07-02-plan-manager`
Execution standard: `docs/standards/planning/atomic_step_execution_standard.yaml`
Inherited base context: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`
G context: `docs/plans/2026-07-02-plan-manager/execution_context/G-007-exchange-format/context.md`
T README: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/README.yaml`
Atomic steps directory: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/atomic_steps`

## Role Boundary

This T branch is a mini/verifier branch only. It must not edit production code directly.
All spark work in this T branch is serialized by the single target-file lock on
`plan_manager/hrs/paragraphs.py`.

## Inherited Rules To Preserve

- Read the execution standard in full before any child action.
- Preserve unrelated dirty worktree changes.
- Do not rewrite HRS prose.
- Do not materialize coverage matrices.
- Re-read artifacts from disk before verification passes.
- Report BLOCKED instead of guessing when contracts are ambiguous or conflicting.
- Each spark agent may edit only the AS target file unless it escalates.

## T-001 Scope

- Target file: `plan_manager/hrs/paragraphs.py`
- Current target file state: `MISSING`
- All four atomic steps target the same file and therefore run strictly in priority order:
  - `A-001`
  - `A-002` depends on `A-001`
  - `A-003` depends on `A-002`
  - `A-004` depends on `A-003`

## Wave Plan

Because all AS in this T branch share one target file, there is no parallelism.
Run each AS only after the previous AS has been implemented and verified:

1. `A-001-create-paragraphs-module-list-paragraphs.yaml`
2. `A-002-add-get-paragraph.yaml`
3. `A-003-add-assign-labels.yaml`
4. `A-004-add-set-non-binding.yaml`

## Shared Target-File Expectations

The file does not exist yet in the repository snapshot.
The first AS must create it from scratch.
Later AS prompts must treat the file content produced by earlier AS steps as the
current ground truth.

## Common Spark Prompt Skeleton

Use this structure for every spark assignment:

```text
First read the execution standard in full: docs/standards/planning/atomic_step_execution_standard.yaml
Then execute this single atomic step.

Role:
You are spark. You are a one-AS coder.

Common owner prompt:
[owner common prompt from the standard]

Per-TS context:
[this file]

Atomic step:
- AS: <AS_ID>
- AS file: <AS_FILE>
- Target file: plan_manager/hrs/paragraphs.py

Current target file state:
[either MISSING for A-001, or the exact current file content produced by prior AS steps]

Worktree note:
Preserve unrelated existing changes.

Required procedure:
1. Implement exactly this AS.
2. Modify only the target file unless the AS is impossible; escalate instead.
3. Preserve unrelated existing changes.
4. Scan the target file for unfinished-code markers: NotImplemented, NotImplementedError, bare pass, TODO, FIXME, stub, and placeholder.
5. Run the verification commands listed for this AS or explain why each cannot run.
6. Return the spark_final_report format.
```

## AS-001

- AS file: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/atomic_steps/A-001-create-paragraphs-module-list-paragraphs.yaml`
- Operation: `create_file`
- Depends on: none
- Target file state for spark: `MISSING`
- Expected result: create `plan_manager/hrs/paragraphs.py` with exactly the module docstring, imports, and `list_paragraphs(...)` function specified in the AS file.
- Current target file state block:

```text
MISSING: plan_manager/hrs/paragraphs.py
```
- Verification:
  - import `plan_manager.hrs.paragraphs`
  - inspect that `list_paragraphs` exists and accepts `(conn, plan_uuid)`
  - run `python -m compileall plan_manager/hrs/paragraphs.py`
  - scan `plan_manager/hrs/paragraphs.py` for unfinished-code markers

## AS-002

- AS file: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/atomic_steps/A-002-add-get-paragraph.yaml`
- Operation: `modify_file`
- Depends on: `A-001`
- Target file state for spark: exact file content produced by `A-001`
- Expected result: append `get_paragraph(...)` exactly as specified in the AS file, without changing any existing text.
- Current target file state block:

```python
"""HRS paragraph access and mutation operations.

Read and mutate stored HRS paragraphs (C-002) through the stored-paragraph
primitives in plan_manager.domain.paragraph_store, and record each
mutation's revision attribution through plan_manager.storage.version_store
(direct mode) or plan_manager.cascade.write (cascade mode).

Only binding paragraphs are ever stored: paragraph_store never holds a
non-binding row. This module defines a function named list_paragraphs that
intentionally shadows the module-level function of the same name in
plan_manager.domain.paragraph_store. The store module is imported by module
name (``from plan_manager.domain import paragraph_store``) and its function
is always called qualified as ``paragraph_store.list_paragraphs(...)`` so
this module's own list_paragraphs never recurses into itself.
"""

import uuid

from plan_manager.domain import paragraph_store


def list_paragraphs(conn, plan_uuid: uuid.UUID) -> list[dict]:
    """Return every stored paragraph of a plan in position order.

    Reads all stored binding paragraphs of the plan identified by
    ``plan_uuid`` through
    ``plan_manager.domain.paragraph_store.list_paragraphs(conn, plan_uuid)``
    and projects each row to a dict with keys "label" (str | None),
    "binding" (bool, always True because only binding paragraphs are ever
    stored), "position" (int), and "text" (str). The store function already
    returns rows in position order; this function preserves that order.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :return: list[dict] -- one dict per stored paragraph, in position order.
    """
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    return [
        {
            "label": row.label,
            "binding": True,
            "position": row.position,
            "text": row.text,
        }
        for row in rows
    ]
```
- Verification:
  - import `plan_manager.hrs.paragraphs`
  - inspect that `get_paragraph` exists and accepts `(conn, plan_uuid, label)`
  - run `python -m compileall plan_manager/hrs/paragraphs.py`
  - scan `plan_manager/hrs/paragraphs.py` for unfinished-code markers

## AS-003

- AS file: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/atomic_steps/A-003-add-assign-labels.yaml`
- Operation: `modify_file`
- Depends on: `A-002`
- Target file state for spark: exact file content produced by `A-002`
- Expected result: add the imports and append `assign_labels(...)` exactly as specified in the AS file, preserving all prior text byte-identically.
- Current target file state block:

```python
"""HRS paragraph access and mutation operations.

Read and mutate stored HRS paragraphs (C-002) through the stored-paragraph
primitives in plan_manager.domain.paragraph_store, and record each
mutation's revision attribution through plan_manager.storage.version_store
(direct mode) or plan_manager.cascade.write (cascade mode).

Only binding paragraphs are ever stored: paragraph_store never holds a
non-binding row. This module defines a function named list_paragraphs that
intentionally shadows the module-level function of the same name in
plan_manager.domain.paragraph_store. The store module is imported by module
name (``from plan_manager.domain import paragraph_store``) and its function
is always called qualified as ``paragraph_store.list_paragraphs(...)`` so
this module's own list_paragraphs never recurses into itself.
"""

import uuid

from plan_manager.domain import paragraph_store


def list_paragraphs(conn, plan_uuid: uuid.UUID) -> list[dict]:
    """Return every stored paragraph of a plan in position order.

    Reads all stored binding paragraphs of the plan identified by
    ``plan_uuid`` through
    ``plan_manager.domain.paragraph_store.list_paragraphs(conn, plan_uuid)``
    and projects each row to a dict with keys "label" (str | None),
    "binding" (bool, always True because only binding paragraphs are ever
    stored), "position" (int), and "text" (str). The store function already
    returns rows in position order; this function preserves that order.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :return: list[dict] -- one dict per stored paragraph, in position order.
    """
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    return [
        {
            "label": row.label,
            "binding": True,
            "position": row.position,
            "text": row.text,
        }
        for row in rows
    ]


def get_paragraph(conn, plan_uuid: uuid.UUID, label: str) -> dict | None:
    """Resolve one stored paragraph by its bare label.

    Calls this module's own list_paragraphs(conn, plan_uuid) and returns
    the single dict whose "label" key equals the given bare ``label``
    string. Returns None when no stored paragraph carries that label.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :param label: str, the bare four-character label to resolve.
    :return: dict | None -- the matching paragraph dict, or None.
    """
    for paragraph in list_paragraphs(conn, plan_uuid):
        if paragraph["label"] == label:
            return paragraph
    return None
```
- Verification:
  - import `plan_manager.hrs.paragraphs`
  - inspect that `assign_labels` exists and accepts `(conn, plan_uuid, author, cascade)`
  - run `python -m compileall plan_manager/hrs/paragraphs.py`
  - scan `plan_manager/hrs/paragraphs.py` for unfinished-code markers

## AS-004

- AS file: `docs/plans/2026-07-02-plan-manager/G-007-exchange-format/T-001-hrs-paragraph-access/atomic_steps/A-004-add-set-non-binding.yaml`
- Operation: `modify_file`
- Depends on: `A-003`
- Target file state for spark: exact file content produced by `A-003`
- Expected result: append `set_non_binding(...)` exactly as specified in the AS file, preserving all prior text byte-identically.
- Current target file state block:

```python
"""HRS paragraph access and mutation operations.

Read and mutate stored HRS paragraphs (C-002) through the stored-paragraph
primitives in plan_manager.domain.paragraph_store, and record each
mutation's revision attribution through plan_manager.storage.version_store
(direct mode) or plan_manager.cascade.write (cascade mode).

Only binding paragraphs are ever stored: paragraph_store never holds a
non-binding row. This module defines a function named list_paragraphs that
intentionally shadows the module-level function of the same name in
plan_manager.domain.paragraph_store. The store module is imported by module
name (``from plan_manager.domain import paragraph_store``) and its function
is always called qualified as ``paragraph_store.list_paragraphs(...)`` so
this module's own list_paragraphs never recurses into itself.
"""

import uuid

from plan_manager.domain import paragraph_store
from plan_manager.domain.labeling import assign_missing_labels
from plan_manager.storage.version_store import record_revision
from plan_manager.domain.plan import get_plan
from plan_manager.cascade.record import CascadeRecord
from plan_manager.cascade.write import cascade_write


def list_paragraphs(conn, plan_uuid: uuid.UUID) -> list[dict]:
    """Return every stored paragraph of a plan in position order.

    Reads all stored binding paragraphs of the plan identified by
    ``plan_uuid`` through
    ``plan_manager.domain.paragraph_store.list_paragraphs(conn, plan_uuid)``
    and projects each row to a dict with keys "label" (str | None),
    "binding" (bool, always True because only binding paragraphs are ever
    stored), "position" (int), and "text" (str). The store function already
    returns rows in position order; this function preserves that order.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :return: list[dict] -- one dict per stored paragraph, in position order.
    """
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    return [
        {
            "label": row.label,
            "binding": True,
            "position": row.position,
            "text": row.text,
        }
        for row in rows
    ]


def get_paragraph(conn, plan_uuid: uuid.UUID, label: str) -> dict | None:
    """Resolve one stored paragraph by its bare label.

    Calls this module's own list_paragraphs(conn, plan_uuid) and returns
    the single dict whose "label" key equals the given bare ``label``
    string. Returns None when no stored paragraph carries that label.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :param label: str, the bare four-character label to resolve.
    :return: dict | None -- the matching paragraph dict, or None.
    """
    for paragraph in list_paragraphs(conn, plan_uuid):
        if paragraph["label"] == label:
            return paragraph
    return None


def assign_labels(
    conn, plan_uuid: uuid.UUID, author: str, cascade: CascadeRecord | None
) -> list[str]:
    """Assign fresh labels to every unlabeled stored binding paragraph.

    Reads every stored paragraph of the plan through
    ``plan_manager.domain.paragraph_store.list_paragraphs(conn, plan_uuid)``,
    then calls ``plan_manager.domain.labeling.assign_missing_labels(rows)``
    which returns ``(labeled, new_labels)``: ``labeled`` is the input list
    with a fresh unique four-character base36 label written into every
    entry whose label was None, in the same order as ``rows``; ``new_labels``
    is the list of newly generated label strings. When ``new_labels`` is
    empty, nothing was unlabeled: this function returns the empty list
    immediately and records no revision.

    Otherwise, for every index i where ``rows[i].label is None``, this
    function issues the plain SQL statement
    ``UPDATE paragraph SET label = %s WHERE uuid = %s`` with parameters
    ``(labeled[i].label, rows[i].uuid)`` through a cursor obtained from
    ``conn.cursor()`` used as a context manager, and builds the paragraph
    node snapshot dict ``{"kind": "paragraph", "uuid": str(rows[i].uuid),
    "plan_uuid": str(plan_uuid), "label": labeled[i].label, "text":
    labeled[i].text, "position": labeled[i].position}`` for that changed
    row.

    Revision attribution rule (binding): when ``cascade`` is None, call
    ``plan_manager.storage.version_store.record_revision(conn, plan_uuid,
    author, message, changes, get_plan(conn, plan_uuid).head_revision_uuid,
    ref_name=None)`` exactly once, where ``changes`` is the list of
    ``(row_uuid, snapshot)`` tuples for every changed row and ``message``
    is the literal string "assign paragraph labels". When ``cascade`` is a
    ``plan_manager.cascade.record.CascadeRecord``, call
    ``plan_manager.cascade.write.cascade_write(conn, plan_uuid, cascade,
    row_uuid, snapshot, [], author, message)`` once per changed row, with
    ``status_updates=[]`` and the same literal ``message``.

    :param conn: an open psycopg 3 database connection.
    :param plan_uuid: uuid.UUID identifying the plan.
    :param author: str, the revision author.
    :param cascade: plan_manager.cascade.record.CascadeRecord | None -- the
        open cascade record, or None for direct head-advancing attribution.
    :return: list[str] -- the freshly generated labels; empty when nothing
        was unlabeled.
    """
    rows = paragraph_store.list_paragraphs(conn, plan_uuid)
    labeled, new_labels = assign_missing_labels(rows)
    if not new_labels:
        return new_labels

    message = "assign paragraph labels"
    changed = [
        (rows[i].uuid, labeled[i])
        for i in range(len(rows))
        if rows[i].label is None
    ]

    with conn.cursor() as cur:
        for row_uuid, new_row in changed:
            cur.execute(
                "UPDATE paragraph SET label = %s WHERE uuid = %s",
                (new_row.label, row_uuid),
            )

    if cascade is None:
        changes = [
            (
                row_uuid,
                {
                    "kind": "paragraph",
                    "uuid": str(row_uuid),
                    "plan_uuid": str(plan_uuid),
                    "label": new_row.label,
                    "text": new_row.text,
                    "position": new_row.position,
                },
            )
            for row_uuid, new_row in changed
        ]
        plan = get_plan(conn, plan_uuid)
        record_revision(
            conn,
            plan_uuid,
            author,
            message,
            changes,
            plan.head_revision_uuid,
            ref_name=None,
        )
    else:
        for row_uuid, new_row in changed:
            snapshot = {
                "kind": "paragraph",
                "uuid": str(row_uuid),
                "plan_uuid": str(plan_uuid),
                "label": new_row.label,
                "text": new_row.text,
                "position": new_row.position,
            }
            cascade_write(
                conn, plan_uuid, cascade, row_uuid, snapshot, [], author, message
            )

    return new_labels
```
- Verification:
  - import `plan_manager.hrs.paragraphs`
  - inspect that `set_non_binding` exists and accepts `(conn, plan_uuid, position, non_binding, author, cascade)`
  - run `python -m compileall plan_manager/hrs/paragraphs.py`
  - scan `plan_manager/hrs/paragraphs.py` for unfinished-code markers

## Verification Gate For T Context

Before reporting this T branch complete, verify:

- every AS file in this T branch was read from disk
- the target file state was re-read from disk before the final verification pass
- no unfinished-code markers remain in the touched target file
- no sibling TS context was introduced
- no unrelated repository files were modified
