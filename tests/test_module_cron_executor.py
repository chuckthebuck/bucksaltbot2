"""Tests for module_cron_executor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def test_calculate_next_run_for_valid_schedule():
    import module_cron_executor

    now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    next_run = module_cron_executor._calculate_next_run("*/5 * * * *", base_time=now)

    assert next_run is not None
    assert next_run > now


def test_calculate_next_run_returns_none_for_invalid_schedule():
    import module_cron_executor

    now = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
    next_run = module_cron_executor._calculate_next_run("invalid schedule", base_time=now)

    assert next_run is None


def test_invoke_module_endpoint_returns_true_on_success():
    import module_cron_executor

    with patch("module_cron_executor.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        result = module_cron_executor._invoke_module_endpoint("/api/v1/module/cron/daily")

    assert result is True
    mock_get.assert_called_once()


def test_invoke_module_endpoint_returns_false_on_4xx():
    import module_cron_executor

    with patch("module_cron_executor.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = module_cron_executor._invoke_module_endpoint("/api/v1/module/cron/daily")

    assert result is False


def test_invoke_module_endpoint_returns_false_on_timeout():
    import module_cron_executor

    with patch("module_cron_executor.requests.get") as mock_get:
        import requests

        mock_get.side_effect = requests.RequestException("timeout")

        result = module_cron_executor._invoke_module_endpoint("/api/v1/module/cron/daily")

    assert result is False


def test_get_overdue_cron_jobs_queries_database():
    import module_cron_executor

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        (1, "mymodule", "daily-sync", "0 1 * * *", "/api/v1/mymodule/cron/sync", 300, 1, None),
    ]

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("module_cron_executor.get_conn", return_value=mock_conn):
        jobs = module_cron_executor._get_overdue_cron_jobs()

    assert len(jobs) == 1
    assert jobs[0]["module_name"] == "mymodule"
    assert jobs[0]["job_name"] == "daily-sync"
    assert jobs[0]["endpoint"] == "/api/v1/mymodule/cron/sync"


def test_update_cron_job_times_updates_database():
    import module_cron_executor

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    now = datetime.now(timezone.utc)
    next_run = datetime(2026, 5, 1, 1, 0, 0, tzinfo=timezone.utc)

    with patch("module_cron_executor.get_conn", return_value=mock_conn):
        module_cron_executor._update_cron_job_times(1, last_run_at=now, next_run_at=next_run)

    mock_cursor.execute.assert_called_once()
    mock_conn.commit.assert_called_once()


def test_run_overdue_module_cron_jobs_executes_and_updates():
    import module_cron_executor

    job_data = {
        "id": 1,
        "module_name": "mymodule",
        "job_name": "daily-sync",
        "schedule": "0 1 * * *",
        "endpoint": "/api/v1/mymodule/cron/sync",
        "timeout_seconds": 300,
        "enabled": True,
        "next_run_at": None,
    }

    with patch("module_cron_executor._get_overdue_cron_jobs", return_value=[job_data]):
        with patch("module_cron_executor._invoke_module_endpoint", return_value=True):
            with patch("module_cron_executor._calculate_next_run") as mock_calc:
                mock_calc.return_value = datetime(2026, 5, 1, 1, 0, 0, tzinfo=timezone.utc)
                with patch("module_cron_executor._update_cron_job_times"):
                    result = module_cron_executor.run_overdue_module_cron_jobs()

    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0
