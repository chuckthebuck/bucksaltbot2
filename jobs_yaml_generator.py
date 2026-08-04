"""Render the generated-module block for Toolforge ``jobs.yaml``.

The current registry rows are an editing/staging surface; Toolforge schedules
only the committed ``jobs.yaml``.  A maintainer must replace the contents of its
``BEGIN/END GENERATED MODULE JOBS`` block with this output, review and commit
the file, then deploy so the normal wrapper flushes and reloads that committed
configuration.  Framework-owned jobs outside the markers are never emitted here.
"""

from typing import Any


def _escape_bash_string(s: str) -> str:
    """Escape one value embedded inside a single-quoted Toolforge command."""
    return s.replace("'", "'\\''")


def list_module_cron_jobs():
    """Read normalized registry jobs without creating a router import cycle."""
    from router.module_registry import list_module_cron_jobs as _list_module_cron_jobs

    return _list_module_cron_jobs()


def _generate_cron_job_entries() -> list[dict[str, Any]]:
    """Build Toolforge entries for jobs enabled at both job and module level."""
    cron_jobs = list_module_cron_jobs()
    entries: list[dict[str, Any]] = []

    for job in cron_jobs:
        if not job.get("enabled") or not job.get("module_enabled", True):
            continue

        module_name = job.get("module_name", "").strip()
        job_name = job.get("job_name", "").strip()
        schedule = job.get("schedule", "").strip()
        handler = str(job.get("handler") or "").strip()
        execution_mode = str(job.get("execution_mode") or "").strip().lower()
        if not execution_mode:
            execution_mode = "handler" if handler else "http"
        timeout_seconds = int(job.get("timeout_seconds", 300))

        if not module_name or not job_name or not schedule:
            continue

        # Build job name: module-jobname (replace slashes/spaces with dashes)
        toolforge_job_name = (
            f"{module_name}-{job_name}"
            .replace("/", "-")
            .replace(" ", "-")
            .replace("_", "-")
        )

        if execution_mode in {"handler", "k8s_job"} and handler:
            # Both names now use the same isolated module_runner process.  The
            # outer timeout is deliberately longer so module_runner can record
            # its own timeout result before Toolforge kills the process.
            supervisor_timeout = timeout_seconds + 10
            run_cmd = (
                "export NOTDEV=1; "
                f"timeout {supervisor_timeout} "
                f"python3 -m module_runner "
                f"--module {_escape_bash_string(module_name)} "
                f"--job {_escape_bash_string(job_name)} "
                "--trigger schedule"
            )
        elif execution_mode == "http":
            # Legacy endpoint-backed cron jobs keep working while modules move
            # to isolated handler jobs. Both values are required so the public
            # trigger cannot become an unauthenticated execution surface.
            run_cmd = (
                'export NOTDEV=1; '
                ': "${MODULE_CRON_BASE_URL:?MODULE_CRON_BASE_URL is required}"; '
                ': "${MODULE_CRON_TOKEN:?MODULE_CRON_TOKEN is required}"; '
                "curl -f -X POST "
                '-H "X-Chuckbot-Cron-Token: ${MODULE_CRON_TOKEN}" '
                f"--max-time {timeout_seconds} "
                '"${MODULE_CRON_BASE_URL%/}'
                f"/api/v1/modules/{_escape_bash_string(module_name)}"
                f'/cron/{_escape_bash_string(job_name)}"'
            )
        else:
            continue

        entry = {
            "name": toolforge_job_name,
            "command": f"bash -c '{_escape_bash_string(run_cmd)}'",
            "schedule": schedule,
            "image": "tool-buckbot/tool-buckbot:latest",
            "cpu": 0.1,
            "mem": "256Mi",
            "mount": "all",
        }
        entries.append(entry)

    return entries


def generate_jobs_yaml_section() -> str:
    """Serialize only module-owned Toolforge entries as reviewable YAML."""
    entries = _generate_cron_job_entries()

    if not entries:
        return "# No module cron jobs to add\n"

    # Keep the emitted field order stable for human review and small Git diffs.
    lines: list[str] = []
    for entry in entries:
        lines.append("- name: " + entry["name"])
        lines.append(f"  command: {entry['command']}")
        lines.append(f"  schedule: \"{entry['schedule']}\"")
        lines.append(f"  image: {entry['image']}")
        lines.append(f"  cpu: {entry['cpu']}")
        lines.append(f"  mem: {entry['mem']}")
        lines.append(f"  mount: {entry['mount']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_jobs_yaml_section())
