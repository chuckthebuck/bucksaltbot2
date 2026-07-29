"""Tests for Toolforge job generation."""

from unittest.mock import patch


def test_generate_jobs_yaml_uses_module_runner_for_handler_jobs():
    import jobs_yaml_generator

    with patch(
        "jobs_yaml_generator.list_module_cron_jobs",
        return_value=[
            {
                "module_name": "four_award",
                "job_name": "four-award-sync",
                "schedule": "*/15 * * * *",
                "handler": "modules.four_award.service:run_four_award_sync",
                "execution_mode": "handler",
                "timeout_seconds": 600,
                "enabled": True,
            }
        ],
    ):
        rendered = jobs_yaml_generator.generate_jobs_yaml_section()

    assert "python3 -m module_runner" in rendered
    assert "- name: four-award-four-award-sync" in rendered
    assert "--module four_award" in rendered
    assert "--job four-award-sync" in rendered
    assert "timeout 610" in rendered
    assert "mount: all" in rendered


def test_generate_jobs_yaml_skips_jobs_for_disabled_modules():
    import jobs_yaml_generator

    with patch(
        "jobs_yaml_generator.list_module_cron_jobs",
        return_value=[
            {
                "module_name": "cleanup",
                "job_name": "sync",
                "schedule": "0 * * * *",
                "handler": "cleanup.service:run",
                "execution_mode": "handler",
                "timeout_seconds": 300,
                "enabled": True,
                "module_enabled": False,
            }
        ],
    ):
        rendered = jobs_yaml_generator.generate_jobs_yaml_section()

    assert rendered == "# No module cron jobs to add\n"


def test_generate_jobs_yaml_honors_http_execution_mode_when_handler_also_exists():
    import jobs_yaml_generator

    with patch(
        "jobs_yaml_generator.list_module_cron_jobs",
        return_value=[
            {
                "module_name": "cleanup",
                "job_name": "sync",
                "schedule": "0 * * * *",
                "endpoint": "/cleanup/sync",
                "handler": "cleanup.service:run",
                "execution_mode": "http",
                "timeout_seconds": 300,
                "enabled": True,
            }
        ],
    ):
        rendered = jobs_yaml_generator.generate_jobs_yaml_section()

    assert "curl -f -X POST" in rendered
    assert "X-Chuckbot-Cron-Token" in rendered
    assert "MODULE_CRON_BASE_URL" in rendered
    assert "MODULE_CRON_TOKEN" in rendered
    assert "python3 -m module_runner" not in rendered
