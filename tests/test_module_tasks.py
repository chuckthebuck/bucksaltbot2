from unittest.mock import patch


def test_process_module_job_run_dispatches_stored_run():
    import module_tasks

    run = {
        "id": 77,
        "module_name": "chuck_file_changer",
        "job_name": "file-change",
        "trigger_type": "manual",
        "triggered_by": "Alice",
    }

    with (
        patch("router.module_registry.get_module_job_run", return_value=run),
        patch("module_runner.run_module_job") as run_module_job,
    ):
        module_tasks.process_module_job_run.run(77)

    run_module_job.assert_called_once_with(
        "chuck_file_changer",
        "file-change",
        run_id=77,
        trigger_type="manual",
        triggered_by="Alice",
    )


def test_process_module_job_run_skips_missing_run():
    import module_tasks

    with (
        patch("router.module_registry.get_module_job_run", return_value=None),
        patch("module_runner.run_module_job") as run_module_job,
    ):
        module_tasks.process_module_job_run.run(404)

    run_module_job.assert_not_called()
