"""Content search layer regression suite (CR-6 G-003/T-002). No live database."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from plan_manager.commands.wish_list_command import WishListCommand
from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.wish import WishItem


class _Searchable(DataclassEntity):
    """Minimal entity with searchable text, used to exercise crud_search."""

    ENTITY_TYPE = "searchable"
    TABLE_NAME = "searchable"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "title", "description", "status", "deleted_at", "updated_at")
    SEARCH_COLUMNS = ("title", "description")
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"


class _Unsearchable(DataclassEntity):
    """Entity that declares no searchable columns."""

    ENTITY_TYPE = "unsearchable"
    TABLE_NAME = "unsearchable"
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid", "status", "deleted_at", "updated_at")
    SEARCH_COLUMNS = ()
    SOFT_DELETE_COLUMN = "deleted_at"
    UPDATED_AT_COLUMN = "updated_at"


class _Column:
    """Stands in for a psycopg column description, which is read by .name."""

    def __init__(self, name: str) -> None:
        self.name = name


def _conn(rows: list[dict]) -> MagicMock:
    """A connection whose execute records the statement and replays rows."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [tuple(row.values()) for row in rows]
    cursor.description = [_Column(name) for name in (rows[0].keys() if rows else ())]
    connection = MagicMock()
    connection.execute.return_value = cursor
    return connection


def _statement(connection: MagicMock) -> str:
    return " ".join(str(connection.execute.call_args.args[0]).split())


def _params(connection: MagicMock) -> list:
    return list(connection.execute.call_args.args[1])


def test_crud_search_generates_ilike_for_substring() -> None:
    conn = _conn([{"uuid": "u", "title": "a foo b", "description": "d",
                   "status": "open", "deleted_at": None, "updated_at": "t"}])
    rows = _Searchable.crud_search(conn, search="foo")

    statement = _statement(conn)
    assert "ILIKE" in statement
    assert statement.count("ILIKE") == len(_Searchable.SEARCH_COLUMNS)
    assert " OR " in statement, "searchable columns must be OR-ed, not AND-ed"
    # The needle is a bind parameter, never interpolated into the statement.
    assert "foo" not in statement
    assert "%foo%" in _params(conn)
    assert rows[0]["matched_column"] == "title"
    assert "foo" in rows[0]["snippet"]


def test_crud_search_generates_posix_regex_operator() -> None:
    conn = _conn([{"uuid": "u", "title": "test one", "description": "d",
                   "status": "open", "deleted_at": None, "updated_at": "t"}])
    rows = _Searchable.crud_search(conn, search_regex=r"^test.*$")

    statement = _statement(conn)
    assert "~*" in statement
    assert "ILIKE" not in statement
    assert r"^test.*$" in _params(conn)
    assert rows[0]["matched_column"] is not None
    assert rows[0]["snippet"] is not None


def test_search_takes_precedence_over_regex() -> None:
    """Both supplied: the substring mode wins, deterministically."""
    conn = _conn([])
    _Searchable.crud_search(conn, search="foo", search_regex=r".*")
    statement = _statement(conn)
    assert "ILIKE" in statement and "~*" not in statement


def test_crud_search_combines_with_attribute_filters() -> None:
    conn = _conn([])
    _Searchable.crud_search(conn, search="foo", filters={"status": "active"})
    statement = _statement(conn)
    assert "status" in statement
    assert " AND " in statement, "the search group must be ANDed with the filters"
    params = _params(conn)
    assert "active" in params and "%foo%" in params


def test_crud_search_excludes_soft_deleted_by_default() -> None:
    # The column name also appears in the SELECT list, so assert on the
    # soft-delete PREDICATE rather than on the bare name.
    predicate = "Identifier('deleted_at'), SQL(' IS NULL')"

    conn = _conn([])
    _Searchable.crud_search(conn, search="foo")
    assert predicate in _statement(conn)

    conn = _conn([])
    _Searchable.crud_search(conn, search="foo", include_deleted=True)
    assert predicate not in _statement(conn)


def test_crud_search_honours_order_and_pagination() -> None:
    conn = _conn([])
    _Searchable.crud_search(conn, search="foo", order_by=["updated_at"], limit=10, offset=5)
    statement = _statement(conn)
    assert "ORDER BY" in statement
    assert "LIMIT" in statement and "OFFSET" in statement
    params = _params(conn)
    assert params[-2:] == [10, 5], "limit and offset must bind after the search value"


def test_crud_search_without_search_behaves_like_crud_list() -> None:
    """Existing callers keep working: no search means no search predicate."""
    conn = _conn([])
    _Searchable.crud_search(conn, filters={"status": "active"})
    statement = _statement(conn)
    assert "ILIKE" not in statement and "~*" not in statement
    # And no match annotation is invented for a plain list.
    conn = _conn([{"uuid": "u", "title": "t", "description": "d",
                   "status": "open", "deleted_at": None, "updated_at": "t"}])
    rows = _Searchable.crud_search(conn)
    assert "matched_column" not in rows[0]


def test_snippet_is_bounded_around_the_match() -> None:
    long_text = "x" * 200 + "middle" + "y" * 200
    conn = _conn([{"uuid": "u", "title": long_text, "description": "d",
                   "status": "open", "deleted_at": None, "updated_at": "t"}])
    rows = _Searchable.crud_search(conn, search="middle")
    snippet = rows[0]["snippet"]
    assert "middle" in snippet
    assert len(snippet) < len(long_text), "the snippet must be bounded, not the whole column"
    assert snippet.startswith("...") and snippet.endswith("...")


def test_matched_column_reports_the_column_that_matched() -> None:
    """A hit in a later searchable column is attributed to that column."""
    conn = _conn([{"uuid": "u", "title": "nothing here", "description": "the needle is here",
                   "status": "open", "deleted_at": None, "updated_at": "t"}])
    rows = _Searchable.crud_search(conn, search="needle")
    assert rows[0]["matched_column"] == "description"
    assert "needle" in rows[0]["snippet"]


def test_search_on_entity_without_search_columns_raises() -> None:
    """Refusing is safer than returning every row.

    An unfiltered result would read as "no text matched" while actually meaning
    "this entity cannot search".
    """
    conn = _conn([])
    with pytest.raises(ValueError) as excinfo:
        _Unsearchable.crud_search(conn, search="foo")
    assert "does not declare SEARCH_COLUMNS" in str(excinfo.value)

    with pytest.raises(ValueError):
        _Unsearchable.crud_search(conn, search_regex=".*")

    # Without a search it still lists normally.
    _Unsearchable.crud_search(conn, filters={"status": "active"})


def test_wish_item_declares_its_text_columns() -> None:
    assert WishItem.SEARCH_COLUMNS == ("title", "description")


def test_wish_list_command_exposes_search_parameters() -> None:
    schema = WishListCommand.get_schema()
    for key in ("search", "search_regex"):
        assert key in schema["properties"], f"wish_list does not expose {key}"
        assert schema["properties"][key]["type"] == "string"
        assert key not in schema.get("required", []), f"{key} must stay optional"

    params = WishListCommand.metadata()["parameters"]
    for key in ("search", "search_regex"):
        assert key in params, f"metadata does not document {key}"
        assert params[key]["required"] is False


def test_wish_list_command_forwards_search_to_the_store(monkeypatch) -> None:
    """The command must actually pass the keywords through, not just declare them."""
    import asyncio
    from contextlib import contextmanager

    from plan_manager.commands import wish_list_command as mod

    captured: dict = {}

    @contextmanager
    def fake_db():
        yield object()

    def fake_page(conn, **kwargs):
        captured.update(kwargs)
        return [], 0

    monkeypatch.setattr(mod, "db_connection", fake_db)
    monkeypatch.setattr(mod, "list_wishes_page", fake_page)
    monkeypatch.setattr(mod, "resolve_anchor_scope", lambda conn, **kw: type(
        "Scope", (), {"anchor_plan_uuid": None, "revision_uuid": None,
                      "step_uuid": None, "project_uuid": None}
    )())

    asyncio.run(WishListCommand().execute(search="needle"))
    assert captured.get("search") == "needle"
    assert captured.get("search_regex") is None

    captured.clear()
    asyncio.run(WishListCommand().execute(search_regex="^n.*e$"))
    assert captured.get("search_regex") == "^n.*e$"
