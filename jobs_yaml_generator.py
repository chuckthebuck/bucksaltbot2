"""Generate Toolforge jobs.yaml entries from module cron registry.

This tool reads the module_cron_jobs table and outputs YAML entries
suitable for inclusion in jobs.yaml. A maintainer should review the output,
add it to the repo, and push to trigger a Toolforge redeploy.
"""

from typing import Any

from router.module_registry import list_module_cron_jobs


def _escape_bash_string(s: str) -> str:
    """Escape a string for use in a bash command."""
    return s.replace("'", "'\\''")


def _generate_cron_job_entries() -> list[dict[str, Any]]:
    """Generate Toolforge job.yaml entries for all enabled module cron jobs."""
    cron_jobs = list_module_cron_jobs()
    entries: list[dict[str, Any]] = []

    for job in cron_jobs:
        if not job.get("enabled"):
            continue

        module_name = job.get("module_name", "").strip()
        job_name = job.get("job_name", "").strip()
        schedule = job.get("schedule", "").strip()
        endpoint = job.get("endpoint", "").strip()
        timeout_seconds = int(job.get("timeout_seconds", 300))

        if not module_name or not job_name or not schedule or not endpoint:
            continue

        # Build job name: module-jobname (replace slashes/spaces with dashes)
        toolforge_job_name = f"{module_name}-{job_name}".replace("/", "-").replace(" ", "-")

        # Build command: curl to the module cron endpoint with a timeout
        # The endpoint is expected to be relative to the module, so we construct the full URL
        curl_cmd = (
            f"curl -f -X POST "
            f"--max-time {timeout_seconds} "
            f"http://localhost:5000/api/v1/modules/{_escape_bash_string(module_name)}/cron/{_escape_bash_string(job_name)}"
        )

        entry = {
            "name": toolforge_job_name,
            "command": f"bash -c '{_escape_bash_string(curl_cmd)}'",
            "schedule": schedule,
            "image": "tool-buckbot/tool-buckbot:latest",
            "cpu": 0.1,
            "mem": "256Mi",
        }
        entries.append(entry)

    return entries


def generate_jobs_yaml_section() -> str:
    """Generate jobs.yaml entries as formatted YAML string."""
    entries = _generate_cron_job_entries()

    if not entries:
        return "# No module cron jobs to add\n"

    # Simple YAML generation (compatible with jobs.yaml format)
    lines: list[str] = []
    for entry in entries:
        lines.append("- name: " + entry["name"])
        lines.append(f"  command: {entry['command']}")
        lines.append(f"  schedule: \"{entry['schedule']}\"")
        lines.append(f"  image: {entry['image']}")
        lines.append(f"  cpu: {entry['cpu']}")
        lines.append(f"  mem: {entry['mem']}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print(generate_jobs_yaml_section())
