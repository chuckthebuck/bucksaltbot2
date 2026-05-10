"""Hard emergency-stop support for framework modules."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
import shutil
import subprocess
from typing import Any

from toolsdb import get_conn
from .module_registry import (
    get_module_definition,
    list_module_cron_jobs,
    request_module_job_runs_cancel,
    set_module_enabled,
)


LOGGER = logging.getLogger(__name__)
KILL_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class KillAttempt:
    command: list[str]
    exit_code: int | None
    output: str
    skipped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "output": self.output,
            "skipped": self.skipped,
        }


def toolforge_job_name(module_name: str, job_name: str) -> str:
    """Return the Toolforge job name generated for a module cron job."""
    return (
        f"{module_name}-{job_name}"
        .replace("/", "-")
        .replace(" ", "-")
        .replace("_", "-")
    )


def _run_kill_command(command: list[str]) -> KillAttempt:
    executable = command[0]
    if shutil.which(executable) is None:
        return KillAttempt(
            command=command,
            exit_code=None,
            output=f"{executable} is not available in this container",
            skipped=True,
        )

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=KILL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [exc.stdout, exc.stderr] if part)
        return KillAttempt(command=command, exit_code=None, output=output or "Timed out")

    output = "\n".join(
        part.strip()
        for part in [completed.stdout, completed.stderr]
        if part and part.strip()
    )
    return KillAttempt(command=command, exit_code=completed.returncode, output=output)


def _kill_toolforge_job(job_name: str) -> list[KillAttempt]:
    attempts = [
        ["toolforge", "jobs", "delete", job_name],
        ["kubectl", "delete", "job", job_name, "--ignore-not-found=true"],
        ["kubectl", "delete", "deployment", job_name, "--ignore-not-found=true"],
        [
            "kubectl",
            "delete",
            "pod",
            "-l",
            f"job-name={job_name}",
            "--ignore-not-found=true",
        ],
        [
            "kubectl",
            "delete",
            "pod",
            "-l",
            f"toolforge.org/job-name={job_name}",
            "--ignore-not-found=true",
        ],
        [
            "kubectl",
            "delete",
            "pod",
            "-l",
            f"name={job_name}",
            "--ignore-not-found=true",
        ],
        [
            "kubectl",
            "delete",
            "pod",
            "-l",
            f"app={job_name}",
            "--ignore-not-found=true",
        ],
    ]
    return [_run_kill_command(command) for command in attempts]


def _cancel_rollback_work() -> dict[str, Any]:
    """Cancel rollback's database-tracked work and purge queued Celery messages."""
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM rollback_jobs
                WHERE status NOT IN ('completed', 'failed', 'canceled')
                """
            )
            job_ids = [int(row[0]) for row in cursor.fetchall()]
            if job_ids:
                placeholders = ", ".join(["%s"] * len(job_ids))
                cursor.execute(
                    f"""
                    UPDATE rollback_job_items
                    SET status='canceled', error='Rollback module emergency stop'
                    WHERE job_id IN ({placeholders})
                      AND status NOT IN ('completed', 'failed', 'canceled')
                    """,
                    tuple(job_ids),
                )
                canceled_items = int(cursor.rowcount)
                cursor.execute(
                    f"""
                    UPDATE rollback_jobs
                    SET status='canceled'
                    WHERE id IN ({placeholders})
                    """,
                    tuple(job_ids),
                )
            else:
                canceled_items = 0
        conn.commit()

    celery_purged = None
    try:
        from app import celery

        celery_purged = celery.control.purge()
    except Exception as exc:  # noqa: BLE001 - estop should continue to kill pods
        celery_purged = f"Celery purge failed: {exc}"

    return {
        "rollback_jobs": job_ids,
        "canceled_items": canceled_items,
        "celery_purged": celery_purged,
    }


def emergency_stop_module(module_name: str, *, actor: str | None = None) -> dict[str, Any]:
    """Disable a module and immediately try to kill its active work."""
    module_name = str(module_name or "").strip()
    if not module_name:
        raise ValueError("module_name is required")
    if get_module_definition(module_name) is None:
        raise ValueError("Module not found")

    set_module_enabled(module_name, False)
    canceled_runs = request_module_job_runs_cancel(module_name)
    module_specific: dict[str, Any] = {}
    if module_name == "rollback":
        module_specific["rollback"] = _cancel_rollback_work()

    kill_results: list[dict[str, Any]] = []
    if os.getenv("MODULE_ESTOP_DISABLE_TOOLFORGE_KILL", "").strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        job_names = {
            toolforge_job_name(job["module_name"], job["job_name"])
            for job in list_module_cron_jobs(module_name)
            if job.get("job_name")
        }
        job_names.update(
            str(run["k8s_job_name"]).strip()
            for run in canceled_runs
            if run.get("k8s_job_name")
        )

        if module_name == "rollback":
            job_names.add("buckbot-celery")

        for job_name in sorted(job_names):
            attempts = _kill_toolforge_job(job_name)
            kill_results.append(
                {
                    "job_name": job_name,
                    "attempts": [attempt.as_dict() for attempt in attempts],
                }
            )
            for attempt in attempts:
                if attempt.exit_code == 0:
                    break

    LOGGER.warning(
        "Module emergency stop requested",
        extra={
            "module_name": module_name,
            "actor": actor,
            "canceled_runs": len(canceled_runs),
            "kill_jobs": [result["job_name"] for result in kill_results],
        },
    )
    return {
        "module": module_name,
        "enabled": False,
        "canceled_runs": canceled_runs,
        "kill_results": kill_results,
        "module_specific": module_specific,
    }
