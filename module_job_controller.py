"""Manual-run controller for Chuck the Buckbot Framework module jobs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback

from router.module_registry import claim_next_queued_module_job_run


def run_once() -> bool:
    run = claim_next_queued_module_job_run()
    if not run:
        return False

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

    subprocess.run(cmd, check=False)
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
