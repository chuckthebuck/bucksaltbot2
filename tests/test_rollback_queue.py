"""Tests for rollback_queue.py – Celery task helpers and process_rollback_job."""

from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_mock_conn():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


def test_resolve_pywikibot_dir_falls_back_from_unwritable_home(monkeypatch):
    import rollback_queue

    monkeypatch.delenv("PYWIKIBOT_DIR", raising=False)
    monkeypatch.setenv("HOME", "/data/project/buckbot")

    attempted: list[str] = []

    def fake_mkdir(path_obj, parents=False, exist_ok=False):
        attempted.append(str(path_obj))
        if str(path_obj).startswith("/data/project"):
            raise PermissionError("denied")

    with patch("rollback_queue.Path.mkdir", new=fake_mkdir):
        resolved = rollback_queue._resolve_pywikibot_dir()

    assert str(resolved) == "/workspace/.pywikibot"
    assert attempted[0] == "/data/project/buckbot/.pywikibot"


# ── _fetch_job ────────────────────────────────────────────────────────────────


def test_fetch_job_returns_job_and_items():
    import rollback_queue

    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = (1, "alice", "queued", 0, 12345)
    mock_cursor.fetchall.return_value = [(10, "File:A.jpg", "Vandal", None)]

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        job, items = rollback_queue._fetch_job(1)

    assert job == (1, "alice", "queued", 0, 12345)
    assert items == [(10, "File:A.jpg", "Vandal", None)]


def test_fetch_job_returns_none_when_not_found():
    import rollback_queue

    mock_conn, mock_cursor = _make_mock_conn()
    mock_cursor.fetchone.return_value = None

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        job, items = rollback_queue._fetch_job(999)

    assert job is None
    assert items == []


# ── _update_job_status ────────────────────────────────────────────────────────


def test_update_job_status_executes_correct_sql():
    import rollback_queue

    mock_conn, mock_cursor = _make_mock_conn()

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        rollback_queue._update_job_status(1, "completed")

    mock_cursor.execute.assert_called_once_with(
        "UPDATE rollback_jobs SET status=%s WHERE id=%s",
        ("completed", 1),
    )
    mock_conn.commit.assert_called_once()


# ── _update_item ──────────────────────────────────────────────────────────────


def test_update_item_sets_status_and_error():
    import rollback_queue

    mock_conn, mock_cursor = _make_mock_conn()

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        rollback_queue._update_item(10, "failed", "some error")

    mock_cursor.execute.assert_called_once_with(
        "UPDATE rollback_job_items SET status=%s, error=%s WHERE id=%s",
        ("failed", "some error", 10),
    )
    mock_conn.commit.assert_called_once()


def test_update_item_accepts_none_error():
    import rollback_queue

    mock_conn, mock_cursor = _make_mock_conn()

    with patch("rollback_queue.get_conn", return_value=mock_conn):
        rollback_queue._update_item(10, "completed", None)

    args = mock_cursor.execute.call_args.args[1]
    assert args[1] is None  # error field is None


# ── process_rollback_job (dry-run) ────────────────────────────────────────────


def test_process_rollback_job_dry_run_completes_without_bot_login():
    """Dry-run jobs must not call _bot_site and must mark all items completed."""
    import rollback_queue

    job = (1, "alice", "queued", 1, 12345)  # dry_run=1
    items = [(10, "File:A.jpg", "Vandal", None), (11, "File:B.jpg", "Vandal", None)]

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status") as mock_update_job,
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site") as mock_bot_site,
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_bot_site.assert_not_called()
    assert mock_update_item.call_count == len(items)
    # Every item must be marked completed
    for c in mock_update_item.call_args_list:
        assert c.args[1] == "completed"
    # Final job status must be "completed"
    final_status_call = mock_update_job.call_args_list[-1]
    assert final_status_call.args[1] == "completed"


def test_process_rollback_job_dry_run_sets_running_then_completed():
    """process_rollback_job transitions: queued → running → completed."""
    import rollback_queue

    job = (1, "alice", "queued", 1, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status") as mock_update_job,
        patch("rollback_queue._update_item"),
        patch("rollback_queue._bot_site"),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    statuses = [c.args[1] for c in mock_update_job.call_args_list]
    assert statuses[0] == "running"
    assert statuses[-1] == "completed"


# ── process_rollback_job (live run with MW action API token) ──────────────────


def test_process_rollback_job_live_run_obtains_mw_rollback_token():
    """Live run must fetch a rollback token from the MW action API via
    site.tokens["rollback"] and pass it to site.simple_request."""
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)  # dry_run=0
    items = [(10, "File:A.jpg", "Vandal", "Custom summary")]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_request = MagicMock()
    mock_site.simple_request.return_value = mock_request

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status"),
        patch("rollback_queue._update_item"),
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_site.simple_request.assert_called_once_with(
        action="rollback",
        title="File:A.jpg",
        user="Vandal",
        token="TOKEN+\\",
        summary="Custom summary; requested-by=alice",
        markbot=True,
        bot=True,
    )
    mock_request.submit.assert_called_once()


def test_process_rollback_job_live_run_uses_default_summary_when_none():
    """When item.summary is None the default summary includes requested_by."""
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_site.simple_request.return_value = MagicMock()

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status"),
        patch("rollback_queue._update_item"),
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    called_summary = mock_site.simple_request.call_args.kwargs["summary"]
    assert "alice" in called_summary


def test_process_rollback_job_live_run_marks_item_completed_on_success():
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_site.simple_request.return_value = MagicMock()

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status"),
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_update_item.assert_called_once_with(10, "completed", None)


def test_process_rollback_job_live_run_marks_item_failed_on_api_error():
    """When the MW API call raises an exception the item is marked failed."""
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_site.simple_request.return_value.submit.side_effect = RuntimeError("API error")

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status") as mock_update_job,
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_update_item.assert_called_once_with(10, "failed", "API error")
    # Final job status should be "failed" since one item failed
    final_status = mock_update_job.call_args_list[-1].args[1]
    assert final_status == "failed"


def test_process_rollback_job_noop_alreadyrolled_treated_as_completed():
    """alreadyrolled API error must be treated as completed, not failed."""
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_site.simple_request.return_value.submit.side_effect = RuntimeError(
        "alreadyrolled: The edit you tried to rollback has already been rolled back."
    )

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status") as mock_update_job,
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    # Item must be completed (error string stored), not failed.
    item_call = mock_update_item.call_args
    assert item_call.args[1] == "completed"
    # Job must finish completed because no item genuinely failed.
    final_status = mock_update_job.call_args_list[-1].args[1]
    assert final_status == "completed"


def test_process_rollback_job_noop_onlyauthor_treated_as_completed():
    """onlyauthor API error must be treated as completed, not failed."""
    import rollback_queue

    job = (1, "alice", "queued", 0, 12345)
    items = [(10, "File:A.jpg", "SoleAuthor", None)]

    mock_site = MagicMock()
    mock_site.tokens = {"rollback": "TOKEN+\\"}
    mock_site.simple_request.return_value.submit.side_effect = RuntimeError(
        "onlyauthor: The only author of the page you tried to rollback is that user."
    )

    with (
        patch("rollback_queue._fetch_job", return_value=(job, items)),
        patch("rollback_queue._update_job_status") as mock_update_job,
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site", return_value=mock_site),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    item_call = mock_update_item.call_args
    assert item_call.args[1] == "completed"
    final_status = mock_update_job.call_args_list[-1].args[1]
    assert final_status == "completed"


def test_process_rollback_job_skips_processing_when_job_not_found():
    """process_rollback_job must return early without touching DB if job is absent."""
    import rollback_queue

    with (
        patch("rollback_queue._fetch_job", return_value=(None, [])),
        patch("rollback_queue._update_job_status") as mock_update_job,
    ):
        rollback_queue.process_rollback_job.run(404)

    mock_update_job.assert_not_called()


def test_process_rollback_job_returns_immediately_when_already_canceled():
    import rollback_queue

    job = (1, "alice", "canceled", 1, 12345)
    with (
        patch("rollback_queue._fetch_job", return_value=(job, [])),
        patch("rollback_queue._update_job_status") as mock_update_job,
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_update_job.assert_not_called()


def test_process_rollback_job_marks_item_canceled_if_job_canceled_mid_run():
    import rollback_queue

    queued_job = (1, "alice", "queued", 1, 12345)
    canceled_job = (1, "alice", "canceled", 1, 12345)
    items = [(10, "File:A.jpg", "Vandal", None)]

    with (
        patch(
            "rollback_queue._fetch_job",
            side_effect=[(queued_job, items), (canceled_job, items)],
        ),
        patch("rollback_queue._update_job_status"),
        patch("rollback_queue._update_item") as mock_update_item,
        patch("rollback_queue._bot_site"),
        patch("rollback_queue._count_batch_jobs", return_value=1),
    ):
        rollback_queue.process_rollback_job.run(1)

    mock_update_item.assert_called_once_with(10, "canceled", "Canceled by requester")


# ── _bot_site raises without credentials ─────────────────────────────────────


def test_bot_site_raises_without_oauth_env_vars(monkeypatch):
    """_bot_site must raise RuntimeError when OAuth credentials are missing."""
    import rollback_queue

    monkeypatch.delenv("CONSUMER_TOKEN", raising=False)
    monkeypatch.delenv("CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ACCESS_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="CONSUMER_TOKEN"):
        rollback_queue._bot_site()


def test_bot_site_logs_in_using_pywikibot_oauth(monkeypatch):
    import rollback_queue

    monkeypatch.setenv("CONSUMER_TOKEN", "ct")
    monkeypatch.setenv("CONSUMER_SECRET", "cs")
    monkeypatch.setenv("ACCESS_TOKEN", "at")
    monkeypatch.setenv("ACCESS_SECRET", "as")

    with patch("rollback_queue.pywikibot.Site") as mock_site_cls:
        mock_site = MagicMock()
        mock_site_cls.return_value = mock_site

        returned = rollback_queue._bot_site()

    mock_site_cls.assert_called_once_with("commons", "commons")
    mock_site.login.assert_called_once_with(oauth_token=("ct", "cs", "at", "as"))
    assert returned is mock_site
