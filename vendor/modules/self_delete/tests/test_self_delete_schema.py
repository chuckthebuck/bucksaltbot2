"""Self Delete owns and initializes its SQL schema independently."""

from unittest.mock import MagicMock

from self_delete.schema import init_schema


def test_module_schema_creates_audit_and_queue_tables():
    """A standalone install can bootstrap all five module-owned tables."""
    cursor = MagicMock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    connection.cursor.return_value.__exit__.return_value = False

    init_schema(lambda: connection)

    executed = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "self_delete_runs" in executed
    assert "self_delete_candidates" in executed
    assert "self_delete_events" in executed
    assert "self_delete_jobs" in executed
    assert "self_delete_job_items" in executed
    connection.commit.assert_called_once_with()
