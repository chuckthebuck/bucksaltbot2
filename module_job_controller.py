"""Manual-run controller for Chuck the Buckbot Framework module jobs."""

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
    try:
        configured = float(os.getenv("MODULE_JOB_CONTROLLER_POLL_SECONDS", "0.5"))
    except ValueError:
        configured = 0.5
    return max(0.1, min(configured, 5.0))


def _signal_process(process: subprocess.Popen, sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except OSError:
        return


def _terminate_process(process: subprocess.Popen) -> None:
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
    run = claim_next_queued_module_job_run()
    if not run:
        return False

    run_claimed_run(run)
    return True


def main() -> int:
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
