"""Module cron job executor.

Runs scheduled cron jobs declared in module manifests by fetching them
from the database and invoking their HTTP endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from croniter import croniter
import requests

from toolsdb import get_conn


class _FallbackLogger:
    """Simple logger fallback for test/dev environments."""

    def __init__(self, name: str):
        self.name = name

    def log(self, message: str) -> None:
        print(f"[{self.name}] {message}")


def _build_logger(name: str):
    """Create logger, falling back to stdout if TOOL_DATA_DIR is not set."""
    if not os.environ.get("TOOL_DATA_DIR"):
        return _FallbackLogger(name)

    try:
        from logger import Logger

        return Logger(name)
    except Exception:
        return _FallbackLogger(name)


logger = _build_logger("module_cron_executor")


def _update_cron_job_times(
    job_id: int,
    last_run_at: datetime | None = None,
    next_run_at: datetime | None = None,
) -> None:
    """Update execution timestamps for a cron job."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE module_cron_jobs
                SET last_run_at=%s, next_run_at=%s
                WHERE id=%s
                """,
                (last_run_at, next_run_at, job_id),
            )
        conn.commit()


def _calculate_next_run(schedule: str, base_time: datetime | None = None) -> datetime | None:
    """Calculate the next run time for a cron schedule."""
    try:
        now = base_time or datetime.now(timezone.utc)
        cron = croniter(schedule, now)
        next_run = cron.get_next(datetime)
        return next_run
    except Exception as exc:
        logger.log(f"Failed to calculate next run for schedule '{schedule}': {exc}")
        return None


def _invoke_module_endpoint(endpoint: str, timeout_seconds: int = 300) -> bool:
    """Call a module cron endpoint and return success status."""
    try:
        base_url = os.getenv("MODULE_CRON_BASE_URL", "http://localhost:5000")
        url = f"{base_url}{endpoint}"

        logger.log(f"Invoking module cron endpoint: {url}")
        response = requests.get(url, timeout=timeout_seconds)

        if response.status_code >= 400:
            logger.log(
                f"Module cron endpoint failed with status {response.status_code}: {url}"
            )
            return False

        logger.log(f"Module cron endpoint succeeded: {url}")
        return True
    except requests.RequestException as exc:
        logger.log(f"Failed to invoke module cron endpoint {endpoint}: {exc}")
        return False
    except Exception as exc:
        logger.log(f"Unexpected error invoking module cron endpoint {endpoint}: {exc}")
        return False


def _get_overdue_cron_jobs() -> list[dict[str, Any]]:
    """Return cron jobs that should run now."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, module_name, job_name, schedule, endpoint,
                       timeout_seconds, enabled, next_run_at
                FROM module_cron_jobs
                WHERE enabled=1
                  AND (next_run_at IS NULL OR next_run_at <= UTC_TIMESTAMP())
                ORDER BY next_run_at ASC
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "module_name": row[1],
            "job_name": row[2],
            "schedule": row[3],
            "endpoint": row[4],
            "timeout_seconds": int(row[5]),
            "enabled": bool(row[6]),
            "next_run_at": row[7],
        }
        for row in rows
    ]


@shared_task(bind=True, max_retries=3, name="module_cron_executor.run_overdue_jobs")
def run_overdue_module_cron_jobs(self) -> dict[str, Any]:
    """Execute all module cron jobs that are due to run."""
    try:
        jobs = _get_overdue_cron_jobs()
        now = datetime.now(timezone.utc)
        results = {
            "total": len(jobs),
            "succeeded": 0,
            "failed": 0,
            "next_check": None,
        }

        for job in jobs:
            try:
                job_id = job["id"]
                module_name = job["module_name"]
                job_name = job["job_name"]
                endpoint = job["endpoint"]
                timeout_seconds = job["timeout_seconds"]
                schedule = job["schedule"]

                logger.log(
                    f"Running cron job: {module_name}/{job_name} (endpoint: {endpoint})"
                )

                success = _invoke_module_endpoint(endpoint, timeout_seconds)

                if success:
                    results["succeeded"] += 1
                else:
                    results["failed"] += 1

                next_run = _calculate_next_run(schedule, now)
                _update_cron_job_times(job_id, last_run_at=now, next_run_at=next_run)

            except Exception as exc:
                results["failed"] += 1
                logger.log(f"Error processing cron job {job['job_name']}: {exc}")

        if jobs:
            next_job = jobs[0]
            next_run = _calculate_next_run(next_job["schedule"], now)
            if next_run:
                results["next_check"] = str(next_run)

        logger.log(
            f"Module cron execution complete: "
            f"{results['succeeded']} succeeded, {results['failed']} failed"
        )

        return results

    except Exception as exc:
        logger.log(f"Fatal error in module cron executor: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, name="module_cron_executor.init_next_run_times")
def initialize_module_cron_next_run_times(self) -> dict[str, int]:
    """Initialize next_run_at timestamps for jobs that have never run.

    This task is meant to be run once during deployment setup.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, schedule
                    FROM module_cron_jobs
                    WHERE next_run_at IS NULL AND enabled=1
                    """
                )
                rows = cursor.fetchall()

        now = datetime.now(timezone.utc)
        initialized = 0

        for job_id, schedule in rows:
            try:
                next_run = _calculate_next_run(schedule, now)
                if next_run:
                    _update_cron_job_times(job_id, next_run_at=next_run)
                    initialized += 1
            except Exception as exc:
                logger.log(f"Failed to initialize cron job {job_id}: {exc}")

        logger.log(f"Initialized next_run_at for {initialized} module cron jobs")
        return {"initialized": initialized}

    except Exception as exc:
        logger.log(f"Fatal error initializing cron next run times: {exc}")
        raise self.retry(exc=exc, countdown=30)
