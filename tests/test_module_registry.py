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
            "entry_point": "handler.py",
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
            "entry_point": "cron.py",
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


def test_parse_module_definition_rejects_api_only_module():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="either a UI or at least one cron job"):
        registry.parse_module_definition(
            {
                "name": "api-only",
                "repo": "https://example.invalid/api-only",
                "entry_point": "handler.py",
            }
        )


def test_parse_module_definition_requires_module_consumer_fields_when_enabled():
    import router.module_registry as registry

    with pytest.raises(ValueError, match="oauth_consumer_key_env"):
        registry.parse_module_definition(
            {
                "name": "managed",
                "repo": "https://example.invalid/managed",
                "entry_point": "handler.py",
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
entry_point = "handler.py"
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
