"""Shared Celery tasks for framework-managed module worker jobs."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="buckbot.process_module_job_run", ignore_result=True)
def process_module_job_run(run_id: int) -> None:
    """Atomically claim a framework run and execute it through its controller."""
    from module_job_controller import run_claimed_run
    from router.module_registry import claim_module_job_run

    # Claiming is the duplicate-delivery guard for late-acknowledged Celery tasks.
    run = claim_module_job_run(int(run_id))
    if run is None:
        return

    run_claimed_run(run)


@shared_task(name="buckbot.process_chuck_file_change_job", ignore_result=True)
def process_chuck_file_change_job(job_id: int) -> None:
    """Dispatch a durable Chuck File Changer queue job in the worker process."""
    from chuck_file_changer.queue import process_file_change_job

    process_file_change_job(int(job_id))
