"""Tests for toolsdb.py – database initialisation and connection helper."""

from unittest.mock import MagicMock, patch


def _make_mock_conn():
    """Return a (mock_conn, mock_cursor) pair with a usable cursor context-manager."""
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def test_init_db_creates_bot_jobs_table():
    """init_db executes a CREATE TABLE statement for bot_jobs."""
    mock_conn, mock_cursor = _make_mock_conn()
    with (
        patch("pymysql.connections.Connection", return_value=mock_conn),
        patch("toolsdb._db_user", return_value="testuser"),
    ):
        import toolsdb

        toolsdb.init_db()
    executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
    assert "bot_jobs" in executed


def test_init_db_creates_bot_job_items_table():
    """init_db executes a CREATE TABLE statement for bot_job_items."""
    mock_conn, mock_cursor = _make_mock_conn()
    with (
        patch("pymysql.connections.Connection", return_value=mock_conn),
        patch("toolsdb._db_user", return_value="testuser"),
    ):
        import toolsdb

        toolsdb.init_db()
    executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
    assert "bot_job_items" in executed


def test_init_db_sets_item_status_default_and_attempts_column():
    """init_db ensures queued default status and attempts tracking exist."""
    mock_conn, mock_cursor = _make_mock_conn()
    with (
        patch("pymysql.connections.Connection", return_value=mock_conn),
        patch("toolsdb._db_user", return_value="testuser"),
    ):
        import toolsdb

        toolsdb.init_db()
    executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
    assert "DEFAULT 'queued'" in executed
    assert "attempts" in executed


def test_init_db_selects_correct_database():
    """init_db USE-s the database scoped to the configured username."""
    mock_conn, mock_cursor = _make_mock_conn()
    with (
        patch("pymysql.connections.Connection", return_value=mock_conn),
        patch("toolsdb._db_user", return_value="testuser"),
    ):
        import toolsdb

        toolsdb.init_db()
    executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
    assert "testuser__match_and_split" in executed


def test_get_conn_returns_a_connection():
    """get_conn returns the pymysql Connection object."""
    mock_conn, mock_cursor = _make_mock_conn()
    with patch("pymysql.connections.Connection", return_value=mock_conn):
        import toolsdb

        conn = toolsdb.get_conn()
    assert conn is mock_conn


def test_get_conn_passes_database_name():
    """get_conn passes the correct database kwarg to Connection."""
    mock_conn, mock_cursor = _make_mock_conn()
    with (
        patch("pymysql.connections.Connection", return_value=mock_conn) as MockConn,
        patch("toolsdb._db_user", return_value="testuser"),
    ):
        import toolsdb

        toolsdb.get_conn()
    # The last Connection() call (from get_conn itself) must carry 'database'.
    last_call_kwargs = MockConn.call_args_list[-1].kwargs
    assert last_call_kwargs.get("database") == "testuser__match_and_split"
