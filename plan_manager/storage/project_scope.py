"""Shared project-scope resolution: transitive project matching via plan.project_ids.

Mechanism for the scope-contract defect family (bug e93dd68d / 8684ea59 follow-on:
`project` becomes a first-class OPTIONAL scope across the runtime work-registry
command surface). A record's project scope is:

    (record's own direct project anchor == project_id)
    OR
    (record's plan anchor is one of the plan uuids bound to project_id)

This module resolves the second half of that OR, reusing the SAME plan.project_ids
text[] column (migration 0003_project_bindings.sql, populated via
plan_project_attach) that project_dependency_list already reads through
(see project_dependency_list_command.py's `bound_project_uuids = [uuid.UUID(pid)
for pid in p.project_ids]`) — just resolved in the opposite direction: given a
project_id, which plans are bound to it.
"""
from __future__ import annotations

import uuid

import psycopg


def resolve_project_plan_uuids(conn: psycopg.Connection, project_id: uuid.UUID) -> set[uuid.UUID]:
    """Return the set of plan UUIDs whose plan.project_ids array contains project_id.

    plan.project_ids stores external analysis-server project UUIDs as text; project_id
    is compared as text against that array. A plan with no bound projects, or with
    project_ids not containing project_id, is simply absent from the returned set —
    there is no error case here (an unknown project_id yields an empty set, not
    an exception; callers scoping a listing by project treat an empty set as "no
    plan is bound to this project", not as an error).
    """
    cur = conn.execute(
        "SELECT uuid FROM plan WHERE %s = ANY(project_ids)",
        (str(project_id),),
    )
    return {row[0] for row in cur.fetchall()}
