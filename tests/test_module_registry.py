"""Tests for router.module_registry – manifest parsing and discovery."""

from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest


def test_parse_module_definition_accepts_ui_module():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "four_award",
            "repo": "https://github.com/example/four-award",
            "entry_point": "handler",
            "ui": True,
            "oauth_consumer_mode": "default",
        }
    )

    assert definition.name == "four_award"
    assert definition.is_ui_enabled is True
    assert definition.is_cron_only is False
    assert definition.redis_namespace == "four_award"
    assert definition.exposes_module_surface is True


def test_parse_module_definition_accepts_cron_only_module():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "cleanup",
            "repo": "https://example.invalid/cleanup",
            "entry_point": "cron",
            "cron": [
                {
                    "name": "daily-cleanup",
                    "schedule": "0 1 * * *",
                    "endpoint": "/api/v1/cleanup/cron/daily",
                }
            ],
        }
    )

    assert definition.is_ui_enabled is False
    assert definition.is_cron_only is True
    assert definition.cron_jobs[0].endpoint == "/api/v1/cleanup/cron/daily"


def test_parse_module_definition_accepts_human_readable_handler_job():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "four_award",
            "repo": "https://example.invalid/four-award",
            "entry_point": "modules.four_award.service:run",
            "jobs": [
                {
                    "name": "sync",
                    "run": "every 15 minutes",
                    "handler": "modules.four_award.service:run",
                    "timeout_seconds": 600,
                }
            ],
        }
    )

    job = definition.cron_jobs[0]
    assert job.schedule_text == "every 15 minutes"
    assert job.schedule == "*/15 * * * *"
    assert job.handler == "modules.four_award.service:run"
    assert job.execution_mode == "handler"
    assert job.concurrency_policy == "forbid"


def test_parse_module_definition_accepts_worker_job():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "file_changer",
            "repo": "https://example.invalid/file-changer",
            "entry_point": "modules.file_changer.service:run",
            "ui": True,
            "worker_jobs": [
                {
                    "name": "file-change",
                    "handler": "modules.file_changer.service:run",
                    "timeout_seconds": 900,
                }
            ],
        }
    )

    assert definition.cron_jobs == ()
    assert len(definition.worker_jobs) == 1
    assert definition.worker_jobs[0].name == "file-change"
    assert definition.worker_jobs[0].handler == "modules.file_changer.service:run"
    assert definition.worker_jobs[0].timeout_seconds == 900


def test_parse_module_definition_accepts_module_rights():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "four_award",
            "repo": "https://example.invalid/four-award",
            "entry_point": "modules.four_award.service:run",
            "ui": True,
            "rights": ["manage", "run-jobs", "edit config"],
        }
    )

    assert definition.rights == ("edit_config", "manage", "run_jobs")
    assert definition.effective_rights == (
        "edit_config",
        "estop",
        "manage",
        "run_jobs",
        "view",
    )


def test_parse_module_definition_ignores_framework_generated_rights():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "rollback",
            "repo": "https://example.invalid/rollback",
            "entry_point": "modules.rollback.blueprint",
            "ui": True,
            "rights": ["view", "estop", "manage"],
        }
    )

    assert definition.rights == ("manage",)
    assert definition.effective_rights == ("estop", "manage", "view")


def test_parse_module_definition_accepts_packaged_frontend_metadata():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "four_award",
            "repo": "https://example.invalid/four-award",
            "entry_point": "chuck_the_4awardhelper.service:run_four_award_sync",
            "ui": True,
            "frontend": {
                "script": "chuck_the_4awardhelper:static/four-award-app.js",
                "styles": ["chuck_the_4awardhelper:static/style.css"],
                "props_id": "four-award-props",
                "mount_id": "four-award-app",
                "docs": "chuck_the_4awardhelper:docs/four_award.md",
                "bundled": True,
            },
        }
    )

    assert definition.frontend is not None
    assert definition.frontend.script == "chuck_the_4awardhelper:static/four-award-app.js"
    assert definition.frontend.styles == ("chuck_the_4awardhelper:static/style.css",)
    assert definition.frontend.docs == "chuck_the_4awardhelper:docs/four_award.md"
    assert definition.frontend.bundled is True


def test_four_award_python_manifest_marks_frontend_bundled():
    from vendor.modules.four_award.modules.four_award.manifest import module_manifest

    import router.module_registry as registry

    definition = registry.parse_module_definition(module_manifest())

    assert definition.frontend is not None
    assert definition.frontend.mount_id == "four-award-app"
    assert definition.frontend.bundled is True


def test_parse_module_definition_rejects_frontend_without_ui():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="frontend assets require ui=true"):
        registry.parse_module_definition(
            {
                "name": "cron_helper",
                "repo": "https://example.invalid/cron-helper",
                "entry_point": "cron_helper.service:run",
                "cron": [
                    {
                        "name": "sync",
                        "run": "every hour",
                        "handler": "cron_helper.service:run",
                    }
                ],
                "frontend": {
                    "script": "cron_helper:static/app.js",
                },
            }
        )


def test_parse_module_definition_rejects_unvalidated_name():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="lowercase snake_case"):
        registry.parse_module_definition(
            {
                "name": "bad-module",
                "repo": "https://example.invalid/bad-module",
                "entry_point": "bad_module",
                "ui": True,
            }
        )


def test_parse_module_definition_rejects_file_entry_point():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="entry_point must start"):
        registry.parse_module_definition(
            {
                "name": "bad_entry",
                "repo": "https://example.invalid/bad-entry",
                "entry_point": "handler.py",
                "ui": True,
            }
        )


def test_parse_module_definition_rejects_api_only_module():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="UI, at least one cron job, or at least one worker job"):
        registry.parse_module_definition(
            {
                "name": "api_only",
                "repo": "https://example.invalid/api-only",
                "entry_point": "handler",
            }
        )


def test_parse_module_definition_requires_module_consumer_fields_when_enabled():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="oauth_consumer_key_env"):
        registry.parse_module_definition(
            {
                "name": "managed",
                "repo": "https://example.invalid/managed",
                "entry_point": "handler",
                "ui": True,
                "oauth_consumer_mode": "module",
            }
        )


def test_discover_module_definitions_loads_toml_manifests(tmp_path: Path):
    import router.module_registry as registry

    module_dir = tmp_path / "modules" / "four_award"
    module_dir.mkdir(parents=True)
    manifest = module_dir / "module.toml"
    manifest.write_text(
        """
name = "four_award"
repo = "https://example.invalid/four_award"
entry_point = "handler"
ui = true
""",
        encoding="utf-8",
    )

    definitions = registry.discover_module_definitions(tmp_path)

    assert len(definitions) == 1
    assert definitions[0].name == "four_award"


def test_upsert_module_definition_persists_cron_jobs_and_registry_rows():
    import router.module_registry as registry

    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    definition = registry.parse_module_definition(
        {
            "name": "cleanup",
            "repo": "https://example.invalid/cleanup",
            "entry_point": "cleanup.handler",
            "cron": [
                {
                    "name": "daily-cleanup",
                    "schedule": "0 1 * * *",
                    "endpoint": "/api/v1/cleanup/cron/daily",
                }
            ],
        }
    )

    with patch("router.module_registry.get_conn", return_value=mock_conn):
        registry.upsert_module_definition(definition, enabled=True)

    executed = " ".join(str(c) for c in mock_cursor.execute.call_args_list)
    assert "module_registry" in executed
    assert "module_cron_jobs" in executed


def test_discover_installed_module_definitions_from_entry_points():
    import router.module_registry as registry

    def module_manifest():
        return {
            "name": "four_award",
            "repo": "https://example.invalid/four-award",
            "entry_point": "chuck_the_4awardhelper.service:run_four_award_sync",
            "jobs": [
                {
                    "name": "sync",
                    "run": "every hour",
                    "handler": "chuck_the_4awardhelper.service:run_four_award_sync",
                }
            ],
        }

    entry_point = MagicMock()
    entry_point.name = "four_award"
    entry_point.load.return_value = module_manifest

    with (
        patch("router.module_registry.metadata.entry_points") as mock_entry_points,
    ):
        mock_entry_points.return_value.select.return_value = [entry_point]
        definitions = registry.discover_installed_module_definitions()

    assert len(definitions) == 1
    assert definitions[0].name == "four_award"
    assert definitions[0].cron_jobs[0].schedule == "0 * * * *"


def test_load_enabled_module_names_reads_file_and_env(tmp_path: Path, monkeypatch):
    import router.module_registry as registry

    enabled_file = tmp_path / "enabled-modules.txt"
    enabled_file.write_text(
        """
# bundled
rollback
four-award  # normalized to four_award
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ENABLED_MODULES", "cleanup")

    assert registry.load_enabled_module_names(enabled_file) == {
        "cleanup",
        "four_award",
        "rollback",
    }


def test_bootstrap_installed_module_definitions_filters_enabled_names():
    import router.module_registry as registry

    four_award = registry.parse_module_definition(
        {
            "name": "four_award",
            "repo": "https://example.invalid/four-award",
            "entry_point": "chuck_the_4awardhelper.service:run",
            "jobs": [
                {
                    "name": "sync",
                    "run": "every hour",
                    "handler": "chuck_the_4awardhelper.service:run",
                }
            ],
        }
    )
    cleanup = registry.parse_module_definition(
        {
            "name": "cleanup",
            "repo": "https://example.invalid/cleanup",
            "entry_point": "cleanup.service:run",
            "jobs": [
                {
                    "name": "daily",
                    "run": "every hour",
                    "handler": "cleanup.service:run",
                }
            ],
        }
    )

    with (
        patch(
            "router.module_registry.discover_installed_module_definitions",
            return_value=[four_award, cleanup],
        ),
        patch("router.module_registry.upsert_module_definition") as mock_upsert,
    ):
        definitions = registry.bootstrap_installed_module_definitions(
            enabled_names={"four_award"}
        )

    assert definitions == [four_award]
    mock_upsert.assert_called_once_with(four_award, enabled=True)
