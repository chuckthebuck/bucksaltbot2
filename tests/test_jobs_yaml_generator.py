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
    assert "mount: all" in rendered
