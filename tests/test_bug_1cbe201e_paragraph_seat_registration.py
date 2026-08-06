"""Regression test for bug 1cbe201e: paragraph seat registration.

Bug 1cbe201e: _ParagraphRow had ENTITY_TYPE=None but REGISTER_IDENTITY left at
inherited default True. On live PG, crud_create's Python-side registration would
insert entity_identity.entity_type=NULL (NOT NULL constraint), crashing para_insert.

Regression: Verify that _ParagraphRow.REGISTER_IDENTITY=False so insert_paragraphs
and single-row inserts do NOT issue entity_identity statements.
"""

import uuid

import pytest

from plan_manager.domain.paragraph_store import _ParagraphRow
from plan_manager.domain.paragraph import Paragraph


def test_paragraph_row_register_identity_is_false():
    """Verify _ParagraphRow has REGISTER_IDENTITY=False to disable Python-side registration.

    Regression for bug 1cbe201e: the seat carries ENTITY_TYPE=None so Python-side
    registration (if enabled) would insert entity_identity.entity_type=NULL,
    violating the NOT NULL constraint on live PG. Identity is registered by the
    DB trigger instead.
    """
    assert _ParagraphRow.REGISTER_IDENTITY is False, (
        "Bug 1cbe201e: _ParagraphRow must have REGISTER_IDENTITY=False. "
        "ENTITY_TYPE=None + Python-side registration would write entity_type NULL "
        "and crash on live PG; the DB trigger owns registration."
    )


def test_paragraph_row_entity_type_is_none():
    """Verify _ParagraphRow.ENTITY_TYPE is None (kept out of catalog resolver)."""
    assert _ParagraphRow.ENTITY_TYPE is None, (
        "_ParagraphRow.ENTITY_TYPE must be None to keep it out of the "
        "entity-type resolver; guard calls name the audit type explicitly."
    )


class _StatementRecorder:
    """Mock connection that records all execute statements for verification."""

    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        # Flatten the SQL for inspection (handles psycopg Composed objects)
        sql_str = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        self.statements.append((sql_str, params))
        return self

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def test_paragraph_row_crud_create_does_not_register_identity():
    """Verify _ParagraphRow.crud_create does not issue entity_identity statements.

    With REGISTER_IDENTITY=False, crud_create must skip the Python-side
    identity registration that would otherwise write entity_type=NULL.
    """
    conn = _StatementRecorder()
    para_uuid = uuid.uuid4()
    plan_uuid = uuid.uuid4()

    _ParagraphRow.crud_create(
        conn,
        {
            "uuid": para_uuid,
            "plan_uuid": plan_uuid,
            "label": "A001",
            "text": "Test paragraph",
            "position": 1,
        },
        returning=False,
    )

    # Verify no entity_identity INSERT statements were issued
    insert_entity_identity_stmts = [
        (sql, params) for sql, params in conn.statements
        if "INSERT INTO entity_identity" in sql.upper()
    ]
    assert len(insert_entity_identity_stmts) == 0, (
        f"Bug 1cbe201e: _ParagraphRow.crud_create should not issue entity_identity "
        f"statements (DB trigger owns registration), but found: "
        f"{insert_entity_identity_stmts}"
    )

    # Verify that a paragraph INSERT was issued
    paragraph_insert_stmts = [
        (sql, params) for sql, params in conn.statements
        if "INSERT INTO" in sql.upper() and "paragraph" in sql.lower()
    ]
    assert len(paragraph_insert_stmts) > 0, (
        "Expected at least one INSERT INTO paragraph statement, but none found"
    )
