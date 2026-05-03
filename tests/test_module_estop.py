"""Tests for hard module emergency stops."""

from unittest.mock import MagicMock, patch


def test_toolforge_job_name_matches_jobs_yaml_generator():
    import router.module_estop as module_estop

    assert (
        module_estop.toolforge_job_name("four_award", "four-award-sync")
        == "four-award-four-award-sync"
    )


def test_emergency_stop_disables_cancels_and_kills_module_jobs():
    import router.module_estop as module_estop

    record = MagicMock()
    with (
        patch("router.module_estop.get_module_definition", return_value=record),
        patch("router.module_estop.set_module_enabled") as set_enabled,
        patch(
            "router.module_estop.request_module_job_runs_cancel",
            return_value=[
                {
                    "id": 12,
                    "module_name": "four_award",
                    "job_name": "four-award-sync",
                    "k8s_job_name": None,
                }
            ],
        ) as cancel_runs,
        patch(
            "router.module_estop.list_module_cron_jobs",
            return_value=[
                {
                    "module_name": "four_award",
                    "job_name": "four-award-sync",
                }
            ],
        ),
        patch("router.module_estop._kill_toolforge_job", return_value=[]) as kill_job,
    ):
        result = module_estop.emergency_stop_module("four_award", actor="Admin")

    set_enabled.assert_called_once_with("four_award", False)
    cancel_runs.assert_called_once_with("four_award")
    kill_job.assert_called_once_with("four-award-four-award-sync")
    assert result["module"] == "four_award"
    assert result["enabled"] is False
    assert len(result["canceled_runs"]) == 1


def test_rollback_emergency_stop_cancels_rollback_work_and_celery_job():
    import router.module_estop as module_estop

    record = MagicMock()
    with (
        patch("router.module_estop.get_module_definition", return_value=record),
        patch("router.module_estop.set_module_enabled"),
        patch("router.module_estop.request_module_job_runs_cancel", return_value=[]),
        patch("router.module_estop.list_module_cron_jobs", return_value=[]),
        patch(
            "router.module_estop._cancel_rollback_work",
            return_value={"rollback_jobs": [1, 2], "canceled_items": 3},
        ) as cancel_rollback,
        patch("router.module_estop._kill_toolforge_job", return_value=[]) as kill_job,
    ):
        result = module_estop.emergency_stop_module("rollback", actor="Admin")

    cancel_rollback.assert_called_once_with()
    kill_job.assert_called_once_with("buckbot-celery")
    assert result["module_specific"]["rollback"]["rollback_jobs"] == [1, 2]
