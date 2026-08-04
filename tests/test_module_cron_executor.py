"""Lock down the inert contract of the retired Celery module cron executor.

The production scheduler is Toolforge plus :mod:`module_runner`; this test does
not exercise scheduling.  It protects the compatibility import and the two
signals legacy callers need to distinguish an intentionally disabled executor
from an enabled pass that happened to find no overdue jobs.
"""


def test_module_cron_executor_is_disabled_compatibility_stub():
    """The retained overdue-job hook must identify itself and dispatch no work."""
    # Import the public compatibility module exactly as historical callers do;
    # replacing it with an internal helper would miss accidental removal.
    import module_cron_executor

    result = module_cron_executor.run_overdue_module_cron_jobs()

    # ``disabled`` communicates retirement, while a zero total proves the stub
    # did not report or synthesize a module execution attempt.
    assert result["disabled"] is True
    assert result["total"] == 0
