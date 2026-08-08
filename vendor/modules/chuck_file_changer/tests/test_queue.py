from chuck_file_changer import queue
from chuck_file_changer.schema import ensure_queue_tables


class Cursor:
    def __init__(self, rows=()):
        self.executed = []
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, params=None):
        self.executed.append((statement, params))

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, rows=()):
        self.cursor_instance = Cursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self.cursor_instance


def test_ensure_queue_tables_creates_module_owned_tables():
    conn = Connection()

    ensure_queue_tables(conn)

    statements = "\n".join(statement for statement, _params in conn.cursor_instance.executed)
    assert "CREATE TABLE IF NOT EXISTS chuck_file_change_jobs" in statements
    assert "CREATE TABLE IF NOT EXISTS chuck_file_change_job_items" in statements


def test_list_file_change_jobs_scopes_history_to_requester(monkeypatch):
    conn = Connection(
        [
            (
                7,
                99,
                "Alice",
                "failed",
                1,
                0,
                "https://example.invalid/source",
                "No targets found",
                12,
                "2026-08-07 10:00:00",
                "2026-08-07 10:01:00",
            )
        ]
    )
    monkeypatch.setattr(queue, "_get_conn", lambda: conn)

    jobs = queue.list_file_change_jobs(requested_by="Alice", limit=500)

    assert jobs == [
        {
            "id": 7,
            "batch_id": 99,
            "requested_by": "Alice",
            "status": "failed",
            "dry_run": True,
            "apply_requested": False,
            "source_url": "https://example.invalid/source",
            "error": "No targets found",
            "total_items": 12,
            "created_at": "2026-08-07 10:00:00",
            "updated_at": "2026-08-07 10:01:00",
        }
    ]
    history_query = conn.cursor_instance.executed[-1]
    assert "WHERE requested_by=%s" in history_query[0]
    assert history_query[1] == ("Alice", 200)
