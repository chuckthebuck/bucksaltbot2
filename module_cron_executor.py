"""Preserve the former Celery cron-executor import surface without dispatching work.

Scheduled module jobs used to be discovered and launched by a periodic Celery
executor in this module.  The current deployment model instead projects enabled
manifest schedules into the checked ``jobs.yaml`` file; Toolforge invokes each
handler in an isolated :mod:`module_runner` process.  Keeping this module and its
two historical callables prevents older imports, task registrations, or rollout
code from failing while making the retired execution path explicitly inert.

Neither function reads ToolsDB, advances a next-run timestamp, queues Celery
work, or invokes a module handler.  Rollback remains the only framework-owned
continuous worker path that uses the shared Celery worker.
"""

from __future__ import annotations


def run_overdue_module_cron_jobs(*_args, **_kwargs) -> dict:
    """Return the legacy executor summary without scanning or launching jobs.

    Positional and keyword arguments are accepted and intentionally ignored so
    callers using an older scheduler signature continue to receive a stable
    response during rolling upgrades.  ``disabled`` distinguishes this result
    from a successful executor pass that merely happened to find no overdue
    work, while all counters remain zero because this compatibility layer must
    never claim an execution attempt.

    Returns:
        A legacy-shaped summary declaring the executor disabled and reporting
        zero total, successful, and failed jobs.
    """
    # Keep the full historical counter shape for monitoring or callers that read
    # individual keys, but provide no bridge back into the removed dispatch path.
    return {
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "disabled": True,
        "detail": "Module cron jobs are run by Toolforge jobs.",
    }


def initialize_module_cron_next_run_times(*_args, **_kwargs) -> dict:
    """Return a disabled initialization result without mutating schedule state.

    Older startup code could call this hook to seed database-backed next-run
    timestamps for the Celery poller.  Toolforge now owns schedule timing, so
    initializing those timestamps would create a second, conflicting scheduler.
    Arguments remain variadic solely for compatibility with historical callers.

    Returns:
        A legacy-shaped result reporting that no rows were initialized because
        the compatibility executor is disabled.
    """
    # A distinct ``disabled`` flag prevents ``initialized == 0`` from being
    # mistaken for an active initializer that simply found no missing rows.
    return {"initialized": 0, "disabled": True}
