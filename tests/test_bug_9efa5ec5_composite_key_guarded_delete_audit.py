"""Regression test for bug 9efa5ec5.

guarded_hard_delete (DataclassEntity.crud_hard_delete) writes its audit row
with entity_id=None whenever the deleted row's identity is a composite key
(not a single uuid.UUID) -- e.g. ref's (plan_uuid, name) or relation's
(plan_uuid, from_concept, to_concept, type). runtime_audit_log.entity_id is
NOT NULL on live PostgreSQL, so that audit INSERT crashed the whole delete
operation there (live-reproduced by R31), even though the fake-connection
unit tests for the guard tolerated a None entity_id and stayed green.

Three W05-routed composite deletes were reverted to their pre-CR-7 raw
statements to fix the regression: version_store.delete_ref,
relation_store.remove_relation, and identity.release_project_reservation
(see the "CR-7 G-004 compatibility note" comment beside each). This test
locks down delete_ref's raw-statement shape: exactly one DELETE, scoped to
(plan_uuid, name), with no audit INSERT and no referrer probe.
"""

from __future__ import annotations

import uuid

from plan_manager.storage.version_store import delete_ref


class _FakeConn:
    """Records every statement passed to execute(); no rows are ever returned."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(str(sql).split()), tuple(params)))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_bug_9efa5ec5_delete_ref_issues_single_raw_delete_no_audit() -> None:
    conn = _FakeConn()
    plan_uuid = uuid.uuid4()
    name = "cascade-ref"

    delete_ref(conn, plan_uuid, name)

    # Exactly one statement: the guarded engine wrapper would additionally
    # probe referrers and issue an audit INSERT into runtime_audit_log.
    assert len(conn.executed) == 1
    statement, params = conn.executed[0]
    assert statement == "DELETE FROM ref WHERE plan_uuid = %s AND name = %s"
    assert params == (plan_uuid, name)
    assert "runtime_audit_log" not in statement
    assert "INSERT" not in statement
