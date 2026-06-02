"""Shared Celery tasks for framework-managed module worker jobs."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="buckbot.process_module_job_run", ignore_result=True)
def process_module_job_run(run_id: int) -> None:
    from module_runner import run_module_job
    from router.module_registry import get_module_job_run

    run = get_module_job_run(int(run_id))
    if run is None:
        return

    run_module_job(
        run["module_name"],
        run["job_name"],
        run_id=int(run_id),
        trigger_type=run.get("trigger_type") or "manual",
        triggered_by=run.get("triggered_by"),
    )
