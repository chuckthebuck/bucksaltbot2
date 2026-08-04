"""Supervise isolated subprocesses for framework-managed module job runs.

The durable registry claims work before this controller starts a subprocess.
The controller then enforces manifest timeouts and cooperative cancellation even
when module code is blocked, while the child runner records normal terminal state.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import traceback

from router.module_registry import (
    claim_next_queued_module_job_run,
    get_module_definition,
    get_module_job_run,
    update_module_job_run,
)


ACTIVE_RUN_STATUSES = {"launching", "running", "cancel_requested"}
TERMINATE_GRACE_SECONDS = 5.0


def _job_timeout_seconds(run: dict) -> int:
    """Return the run's manifest timeout or a conservative missing-record default."""
    record = get_module_definition(run["module_name"])
    if record is None:
        return 300
    job = next(
        (
            item
            for item in (*record.definition.cron_jobs, *record.definition.worker_jobs)
            if item.name == run["job_name"]
        ),
        None,
    )
    return int(job.timeout_seconds) if job is not None else 300


def _poll_seconds() -> float:
    """Return the bounded cancellation/timeout polling interval."""
    try:
        configured = float(os.getenv("MODULE_JOB_CONTROLLER_POLL_SECONDS", "0.5"))
    except ValueError:
        configured = 0.5
    return max(0.1, min(configured, 5.0))


def _signal_process(process: subprocess.Popen, sig: signal.Signals) -> None:
    """Signal the child process group when supported, ignoring exited races."""
    if process.poll() is not None:
        return
    try:
        # The runner can create its own descendants, so POSIX supervision targets
        # the fresh process group rather than leaving grandchildren alive.
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except OSError:
        return


def _terminate_process(process: subprocess.Popen) -> None:
    """Request graceful termination, then force-kill after the grace period."""
    _signal_process(process, signal.SIGTERM)
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass
    _signal_process(process, signal.SIGKILL)
    process.wait()


def _update_if_active(
    run_id: int,
    *,
    status: str,
    error: str,
    exit_code: int,
) -> None:
    """Write a terminal outcome only if no competing path already finished it."""
    current = get_module_job_run(run_id)
    if current and current.get("status") in ACTIVE_RUN_STATUSES:
        update_module_job_run(
            run_id,
            status=status,
            error=error,
            exit_code=exit_code,
        )


def run_claimed_run(run: dict) -> int:
    """Execute one already-claimed run with hard timeout and cancellation."""
    run_id = int(run["id"])
    current = get_module_job_run(run_id) or run
    if current.get("status") in {"cancel_requested", "canceled"}:
        _update_if_active(
            run_id,
            status="canceled",
            error=f"Run {run_id} was canceled before launch",
            exit_code=130,
        )
        return 130

    cmd = [
        sys.executable,
        "-m",
        "module_runner",
        "--module",
        run["module_name"],
        "--job",
        run["job_name"],
        "--run-id",
        str(run["id"]),
        "--trigger",
        run.get("trigger_type") or "manual",
    ]
    triggered_by = run.get("triggered_by")
    if triggered_by:
        cmd.extend(["--triggered-by", triggered_by])

    timeout_seconds = _job_timeout_seconds(run)
    try:
        process = subprocess.Popen(
            cmd,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        _update_if_active(
            run_id,
            status="failed",
            error=f"Failed to launch module runner: {exc}",
            exit_code=127,
        )
        return 127

    # Monotonic time is immune to NTP/system-clock changes during long jobs.
    deadline = time.monotonic() + timeout_seconds
    poll_seconds = _poll_seconds()

    try:
        while process.poll() is None:
            current = get_module_job_run(run_id) or {}
            if current.get("status") in {"cancel_requested", "canceled"}:
                _terminate_process(process)
                _update_if_active(
                    run_id,
                    status="canceled",
                    error=f"Run {run_id} was canceled",
                    exit_code=130,
                )
                return 130
            if time.monotonic() >= deadline:
                _terminate_process(process)
                _update_if_active(
                    run_id,
                    status="failed",
                    error=f"Module job timed out after {timeout_seconds} seconds",
                    exit_code=124,
                )
                return 124
            time.sleep(poll_seconds)
    except Exception:
        _terminate_process(process)
        raise

    exit_code = int(process.returncode or 0)
    current = get_module_job_run(run_id) or {}
    if current.get("status") in ACTIVE_RUN_STATUSES:
        # A zero-exit child must have recorded completion itself.  Treat a still-
        # active row as a protocol failure rather than silently losing the run.
        if exit_code == 0:
            _update_if_active(
                run_id,
                status="failed",
                error="Module runner exited without recording a terminal state",
                exit_code=1,
            )
            return 1
        _update_if_active(
            run_id,
            status="failed",
            error=f"Module runner exited with code {exit_code}",
            exit_code=exit_code,
        )
    return exit_code


def run_once() -> bool:
    """Claim and supervise at most one queued run, reporting whether work existed."""
    run = claim_next_queued_module_job_run()
    if not run:
        return False

    run_claimed_run(run)
    return True


def main() -> int:
    """Run one controller iteration or poll indefinitely for queued module work."""
    os.environ.setdefault("NOTDEV", "1")
    sleep_seconds = int(os.getenv("MODULE_JOB_CONTROLLER_SLEEP", "15"))
    once = "--once" in sys.argv

    while True:
        try:
            did_work = run_once()
        except Exception:  # noqa: BLE001 - controller must survive transient infra errors
            traceback.print_exc()
            did_work = False
            if once:
                return 1

        if once:
            return 0 if did_work else 1

        if not did_work:
            time.sleep(max(1, sleep_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
