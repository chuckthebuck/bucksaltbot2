"""Compatibility stub for the removed Celery module cron executor.

Module schedules are now run by Toolforge jobs through ``module_runner``.
Rollback remains the only Celery-backed continuous worker path.
"""

from __future__ import annotations


def run_overdue_module_cron_jobs(*_args, **_kwargs) -> dict:
    return {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "disabled": True,
        "detail": "Module cron jobs are run by Toolforge jobs.",
    }


def initialize_module_cron_next_run_times(*_args, **_kwargs) -> dict:
    return {"initialized": 0, "disabled": True}

