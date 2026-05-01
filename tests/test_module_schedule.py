"""Tests for Chuck the Buckbot Framework schedule parsing."""

import pytest


def test_human_schedule_to_cron_interval_minutes():
    from router.module_schedule import human_schedule_to_cron

    assert human_schedule_to_cron("every 15 minutes") == "*/15 * * * *"


def test_human_schedule_to_cron_daily_time():
    from router.module_schedule import human_schedule_to_cron

    assert human_schedule_to_cron("daily at 03:30") == "30 3 * * *"


def test_human_schedule_to_cron_weekly_time():
    from router.module_schedule import human_schedule_to_cron

    assert human_schedule_to_cron("weekly on monday at 09:05") == "5 9 * * 1"


def test_human_schedule_to_cron_rejects_loose_language():
    from router.module_schedule import human_schedule_to_cron

    with pytest.raises(ValueError, match="unsupported run schedule"):
        human_schedule_to_cron("whenever the wiki feels quiet")


def test_human_schedule_to_cron_interval_hours():
    from router.module_schedule import human_schedule_to_cron

    assert human_schedule_to_cron("every 6 hours") == "0 */6 * * *"
