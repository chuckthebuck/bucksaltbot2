"""Compatibility tests for the removed Celery module cron executor."""


def test_module_cron_executor_is_disabled_compatibility_stub():
    import module_cron_executor

    result = module_cron_executor.run_overdue_module_cron_jobs()

    assert result["disabled"] is True
    assert result["total"] == 0

