from pathlib import Path
from unittest.mock import patch


def test_process_module_job_run_claims_and_dispatches_stored_run():
    import module_tasks

    run = {
        "id": 77,
        "module_name": "chuck_file_changer",
        "job_name": "file-change",
        "trigger_type": "manual",
        "triggered_by": "Alice",
    }

    with (
        patch("router.module_registry.claim_module_job_run", return_value=run),
        patch("module_job_controller.run_claimed_run") as run_claimed_run,
    ):
        module_tasks.process_module_job_run.run(77)

    run_claimed_run.assert_called_once_with(run)


def test_process_module_job_run_skips_missing_run():
    import module_tasks

    with (
        patch("router.module_registry.claim_module_job_run", return_value=None),
        patch("module_job_controller.run_claimed_run") as run_claimed_run,
    ):
        module_tasks.process_module_job_run.run(404)

    run_claimed_run.assert_not_called()


def test_process_chuck_file_change_job_dispatches_queue_processor(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[1] / "vendor/modules/chuck_file_changer/modules")
    )
    import module_tasks

    with patch("chuck_file_changer.queue.process_file_change_job") as process_job:
        module_tasks.process_chuck_file_change_job.run(42)

    process_job.assert_called_once_with(42)
