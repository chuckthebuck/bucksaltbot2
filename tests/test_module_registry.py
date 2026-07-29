"""Tests for router.module_registry – manifest parsing and discovery."""

from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest


def _module_run_row(run_id: int, result_json: str) -> tuple:
    return (
        run_id,
        "four_award",
        "sync",
        "completed",
        "schedule",
        None,
        None,
        None,
        None,
        0,
        None,
        "{}",
        result_json,
        None,
    )


def test_list_module_job_runs_non_blank_pages_until_requested_hits():
    import router.module_registry as registry

    class FakeCursor:
        def __init__(self, pages):
            self.pages = pages
            self.executed = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query, params):
            self.executed.append((query, params))

        def fetchall(self):
            return self.pages.pop(0)

    class FakeConn:
        def __init__(self, pages):
            self.cursor_obj = FakeCursor(pages)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def cursor(self):
            return self.cursor_obj

    pages = [
        [
            _module_run_row(4, '{"run_kind": "empty", "has_nominations": false}'),
            _module_run_row(3, '{"has_nominations": true, "nomination_count": 1}'),
        ],
        [
            _module_run_row(2, '{"run_kind": "empty", "has_nominations": false}'),
            _module_run_row(1, '{"dry_run_edits": [{"title": "Wikipedia:Four Award"}]}'),
        ],
    ]
    conn = FakeConn(pages)

    with patch("router.module_registry.get_conn", return_value=conn):
        runs = registry.list_module_job_runs(
            "four_award",
            limit=2,
            non_blank=True,
            scan_limit=4,
        )

    assert [run["id"] for run in runs] == [3, 1]
    assert [params[-2:] for _, params in conn.cursor_obj.executed] == [(2, 0), (2, 2)]


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


def test_parse_module_definition_rejects_remote_cron_endpoint():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="application path"):
        registry.parse_module_definition(
            {
                "name": "cleanup",
                "repo": "https://example.invalid/cleanup",
                "entry_point": "cleanup.cron",
                "cron": [
                    {
                        "name": "daily-cleanup",
                        "schedule": "0 1 * * *",
                        "endpoint": "https://example.invalid/run",
                    }
                ],
            }
        )


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


def test_parse_module_definition_accepts_job_required_right():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "file_changer",
            "repo": "https://example.invalid/file-changer",
            "entry_point": "modules.file_changer.service:run",
            "ui": True,
            "rights": ["apply_changes"],
            "worker_jobs": [
                {
                    "name": "file-change",
                    "handler": "modules.file_changer.service:run",
                    "required_right": "apply-changes",
                }
            ],
        }
    )

    assert definition.worker_jobs[0].required_right == "apply_changes"


def test_parse_module_definition_rejects_undeclared_job_required_right():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="must also appear in module rights"):
        registry.parse_module_definition(
            {
                "name": "file_changer",
                "repo": "https://example.invalid/file-changer",
                "entry_point": "file_changer.service:run",
                "worker_jobs": [
                    {
                        "name": "apply",
                        "handler": "file_changer.service:run",
                        "required_right": "apply_changes",
                    }
                ],
            }
        )


def test_parse_module_definition_rejects_duplicate_job_names_across_job_types():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="job names must be unique"):
        registry.parse_module_definition(
            {
                "name": "cleanup",
                "repo": "https://example.invalid/cleanup",
                "entry_point": "cleanup.service:run",
                "jobs": [
                    {
                        "name": "sync",
                        "run": "every hour",
                        "handler": "cleanup.service:run",
                    }
                ],
                "worker_jobs": [
                    {
                        "name": "sync",
                        "handler": "cleanup.service:run",
                    }
                ],
            }
        )


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


def test_four_award_python_entry_point_uses_packaged_toml_manifest():
    from vendor.modules.four_award.modules.four_award.manifest import module_manifest

    import router.module_registry as registry

    definition = registry.parse_module_definition(module_manifest())
    toml_definition = registry.load_module_definition(
        Path(
            "vendor/modules/four_award/modules/four_award/module.toml"
        )
    )

    assert definition == toml_definition
    assert definition.frontend.mount_id == "four-award-app"
    assert definition.frontend.bundled is True


def test_file_changer_python_entry_point_uses_packaged_toml_manifest():
    from vendor.modules.chuck_file_changer.modules.chuck_file_changer.manifest import (
        module_manifest,
    )

    import router.module_registry as registry

    definition = registry.parse_module_definition(module_manifest())
    toml_definition = registry.load_module_definition(
        Path(
            "vendor/modules/chuck_file_changer/modules/"
            "chuck_file_changer/module.toml"
        )
    )

    assert definition == toml_definition


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


def test_parse_module_definition_records_module_worker_oauth_environment():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "managed",
            "repo": "https://example.invalid/managed",
            "entry_point": "handler",
            "ui": True,
            "oauth_consumer_mode": "module",
            "oauth_consumer_key_env": "MANAGED_CONSUMER_TOKEN",
            "oauth_consumer_secret_env": "MANAGED_CONSUMER_SECRET",
            "oauth_access_token_env": "MANAGED_ACCESS_TOKEN",
            "oauth_access_secret_env": "MANAGED_ACCESS_SECRET",
        }
    )

    assert definition.oauth_consumer_key_env == "MANAGED_CONSUMER_TOKEN"
    assert definition.oauth_consumer_secret_env == "MANAGED_CONSUMER_SECRET"
    assert definition.oauth_access_token_env == "MANAGED_ACCESS_TOKEN"
    assert definition.oauth_access_secret_env == "MANAGED_ACCESS_SECRET"


def test_parse_module_definition_rejects_invalid_oauth_environment_name():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="uppercase environment variable"):
        registry.parse_module_definition(
            {
                "name": "managed",
                "repo": "https://example.invalid/managed",
                "entry_point": "handler",
                "ui": True,
                "oauth_consumer_mode": "module",
                "oauth_consumer_key_env": "not-valid",
                "oauth_consumer_secret_env": "MANAGED_CONSUMER_SECRET",
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


def test_upsert_module_definition_preserves_runtime_state():
    import json

    import router.module_registry as registry

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("daily-cleanup", "*/5 * * * *", "every 5 minutes", 45, 0)
    ]
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
                    "timeout_seconds": 300,
                }
            ],
        }
    )

    with patch("router.module_registry.get_conn", return_value=mock_conn):
        registry.upsert_module_definition(definition, enabled=True)

    registry_insert = next(
        call
        for call in mock_cursor.execute.call_args_list
        if "INSERT INTO module_registry" in call.args[0]
    )
    persisted_manifest = json.loads(registry_insert.args[1][-1])
    persisted_job = persisted_manifest["cron_jobs"][0]
    assert persisted_job["schedule"] == "*/5 * * * *"
    assert persisted_job["schedule_text"] == "every 5 minutes"
    assert persisted_job["timeout_seconds"] == 45
    assert persisted_job["enabled"] is False
    assert "enabled=VALUES(enabled)" not in registry_insert.args[0]


def test_update_module_cron_job_preserves_worker_jobs():
    import json

    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "combined",
            "repo": "https://example.invalid/combined",
            "entry_point": "combined.service:run",
            "jobs": [
                {
                    "name": "scheduled",
                    "run": "every hour",
                    "handler": "combined.service:run",
                }
            ],
            "worker_jobs": [
                {
                    "name": "manual",
                    "handler": "combined.service:run",
                }
            ],
        }
    )
    record = registry.ModuleRecord(definition=definition, enabled=True)
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("router.module_registry.get_module_definition", return_value=record),
        patch("router.module_registry.get_conn", return_value=mock_conn),
    ):
        registry.update_module_cron_job(
            "combined",
            "scheduled",
            schedule_text="every 5 minutes",
        )

    manifest_update = next(
        call
        for call in mock_cursor.execute.call_args_list
        if "UPDATE module_registry" in call.args[0]
    )
    persisted_manifest = json.loads(manifest_update.args[1][0])
    assert persisted_manifest["worker_jobs"][0]["name"] == "manual"


def test_create_module_job_run_forbid_rejects_active_run():
    import router.module_registry as registry

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(12,)]
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("router.module_registry.get_conn", return_value=mock_conn),
        pytest.raises(registry.ModuleJobConcurrencyError) as exc_info,
    ):
        registry.create_module_job_run(
            "cleanup",
            "sync",
            concurrency_policy="forbid",
        )

    assert exc_info.value.active_run_ids == [12]
    mock_conn.rollback.assert_called_once()
    assert not any(
        "INSERT INTO module_job_runs" in call.args[0]
        for call in mock_cursor.execute.call_args_list
    )


def test_create_module_job_run_replace_cancels_active_and_inserts():
    import router.module_registry as registry

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [(12,), (13,)]
    mock_cursor.lastrowid = 99
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("router.module_registry.get_conn", return_value=mock_conn):
        run_id = registry.create_module_job_run(
            "cleanup",
            "sync",
            concurrency_policy="replace",
        )

    assert run_id == 99
    executed = " ".join(call.args[0] for call in mock_cursor.execute.call_args_list)
    assert "SELECT name" in executed
    assert "FROM module_registry" in executed
    assert "FOR UPDATE" in executed
    assert "UPDATE module_job_runs" in executed
    assert "INSERT INTO module_job_runs" in executed
    replace_call = next(
        call
        for call in mock_cursor.execute.call_args_list
        if "UPDATE module_job_runs" in call.args[0]
    )
    assert replace_call.args[1][0] == "Replaced by a newer module job run"


def test_claim_module_job_run_atomically_claims_queued_run():
    import router.module_registry as registry

    run = {"id": 77, "status": "launching"}
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("router.module_registry.get_conn", return_value=mock_conn),
        patch("router.module_registry.get_module_job_run", return_value=run),
    ):
        claimed = registry.claim_module_job_run(77)

    assert claimed == run
    assert "status='queued'" in mock_cursor.execute.call_args.args[0]
    mock_conn.commit.assert_called_once()


def test_claim_module_job_run_rejects_already_claimed_run():
    import router.module_registry as registry

    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("router.module_registry.get_conn", return_value=mock_conn),
        patch("router.module_registry.get_module_job_run") as get_run,
    ):
        claimed = registry.claim_module_job_run(77)

    assert claimed is None
    get_run.assert_not_called()


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


def test_bootstrap_installed_module_definitions_respects_empty_enabled_allowlist():
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "cleanup",
            "repo": "https://example.invalid/cleanup",
            "entry_point": "cleanup.service:run",
            "worker_jobs": [
                {
                    "name": "sync",
                    "handler": "cleanup.service:run",
                }
            ],
        }
    )

    with (
        patch(
            "router.module_registry.discover_installed_module_definitions",
            return_value=[definition],
        ),
        patch("router.module_registry.upsert_module_definition") as mock_upsert,
    ):
        definitions = registry.bootstrap_installed_module_definitions(
            enabled_names=set()
        )

    assert definitions == []
    mock_upsert.assert_not_called()
