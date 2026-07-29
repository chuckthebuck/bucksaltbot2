from unittest.mock import patch

import pytest


def test_run_module_job_executes_worker_job_handler():
    import module_runner
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "chuck_file_changer",
            "repo": "https://example.invalid/chuck-file-changer",
            "entry_point": "chuck_file_changer.service:run_file_change",
            "ui": True,
            "worker_jobs": [
                {
                    "name": "file-change",
                    "handler": "chuck_file_changer.service:run_file_change",
                }
            ],
        }
    )
    record = registry.ModuleRecord(definition=definition, enabled=True)

    def handler(ctx, payload):
        return {"run_id": ctx.run_id, "payload": payload}

    with (
        patch("module_runner.ensure_pywikibot_env"),
        patch("module_runner._bootstrap_local_registry"),
        patch("module_runner.get_module_definition", return_value=record),
        patch("module_runner.get_module_job_run", return_value={"payload": {"x": 1}}),
        patch("module_runner.get_module_config", return_value={}),
        patch("module_runner._import_handler", return_value=handler),
        patch("module_runner.update_module_job_run") as update_run,
    ):
        exit_code = module_runner.run_module_job(
            "chuck_file_changer",
            "file-change",
            run_id=123,
            trigger_type="manual",
            triggered_by="Alice",
        )

    assert exit_code == 0
    update_run.assert_any_call(123, status="running")
    update_run.assert_any_call(
        123,
        status="completed",
        exit_code=0,
        result={"run_id": 123, "payload": {"x": 1}},
    )


def test_run_module_job_does_not_revive_canceled_worker_run():
    import module_runner
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "chuck_file_changer",
            "repo": "https://example.invalid/chuck-file-changer",
            "entry_point": "chuck_file_changer.service:run_file_change",
            "ui": True,
            "worker_jobs": [
                {
                    "name": "file-change",
                    "handler": "chuck_file_changer.service:run_file_change",
                }
            ],
        }
    )
    record = registry.ModuleRecord(definition=definition, enabled=True)

    with (
        patch("module_runner.ensure_pywikibot_env"),
        patch("module_runner._bootstrap_local_registry"),
        patch("module_runner.get_module_definition", return_value=record),
        patch("module_runner.get_module_job_run", return_value={"status": "canceled"}),
        patch("module_runner._import_handler") as import_handler,
        patch("module_runner.update_module_job_run") as update_run,
    ):
        exit_code = module_runner.run_module_job(
            "chuck_file_changer",
            "file-change",
            run_id=123,
            trigger_type="manual",
            triggered_by="Alice",
        )

    assert exit_code == 130
    import_handler.assert_not_called()
    update_run.assert_called_once_with(
        123,
        status="canceled",
        error="Run 123 was canceled",
        exit_code=130,
    )


def test_run_module_job_records_handler_timeout():
    import module_runner
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
                    "timeout_seconds": 15,
                }
            ],
        }
    )
    record = registry.ModuleRecord(definition=definition, enabled=True)

    with (
        patch("module_runner.ensure_pywikibot_env"),
        patch("module_runner._bootstrap_local_registry"),
        patch("module_runner.get_module_definition", return_value=record),
        patch("module_runner.get_module_job_run", return_value={"payload": {}}),
        patch("module_runner.get_module_config", return_value={}),
        patch("module_runner._import_handler", return_value=lambda: None),
        patch(
            "module_runner._invoke_handler",
            side_effect=module_runner.ModuleRunTimedOut(
                "Module job timed out after 15 seconds"
            ),
        ),
        patch("module_runner.update_module_job_run") as update_run,
    ):
        exit_code = module_runner.run_module_job(
            "cleanup",
            "sync",
            run_id=123,
            trigger_type="manual",
        )

    assert exit_code == 124
    update_run.assert_any_call(
        123,
        status="failed",
        error="Module job timed out after 15 seconds",
        exit_code=124,
    )


@pytest.mark.parametrize(
    ("parameter_name", "expected"),
    [
        ("ctx", "context"),
        ("payload", {"x": 1}),
    ],
)
def test_invoke_handler_supports_single_argument_handlers(parameter_name, expected):
    import module_runner

    context = object()
    payload = {"x": 1}
    namespace = {}
    exec(
        f"def handler({parameter_name}):\n"
        f"    return {parameter_name}\n",
        namespace,
    )

    result = module_runner._invoke_handler(
        namespace["handler"],
        context,
        payload,
    )

    assert result == (context if expected == "context" else expected)


def test_invoke_handler_rejects_unsupported_signature():
    import module_runner

    def handler(first, second, third):
        return first, second, third

    with pytest.raises(ValueError, match="must accept"):
        module_runner._invoke_handler(handler, object(), {})


def test_config_view_is_a_read_only_mapping():
    import module_runner

    config = module_runner._ConfigView({"dry_run": True})

    assert config["dry_run"] is True
    assert dict(config) == {"dry_run": True}
    assert config.as_dict() == {"dry_run": True}


def test_json_safe_result_normalizes_custom_values():
    import module_runner

    result = module_runner._json_safe_result({"value": object()})

    assert isinstance(result["value"], str)


def test_activate_module_oauth_maps_isolated_credentials(monkeypatch):
    import module_runner
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "managed",
            "repo": "https://example.invalid/managed",
            "entry_point": "managed.service:run",
            "worker_jobs": [
                {
                    "name": "sync",
                    "handler": "managed.service:run",
                }
            ],
            "oauth_consumer_mode": "module",
            "oauth_consumer_key_env": "MANAGED_CONSUMER_TOKEN",
            "oauth_consumer_secret_env": "MANAGED_CONSUMER_SECRET",
            "oauth_access_token_env": "MANAGED_ACCESS_TOKEN",
            "oauth_access_secret_env": "MANAGED_ACCESS_SECRET",
        }
    )
    values = {
        "MANAGED_CONSUMER_TOKEN": "consumer-token",
        "MANAGED_CONSUMER_SECRET": "consumer-secret",
        "MANAGED_ACCESS_TOKEN": "access-token",
        "MANAGED_ACCESS_SECRET": "access-secret",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    module_runner._activate_module_oauth(definition)

    assert module_runner.os.environ["CONSUMER_TOKEN"] == "consumer-token"
    assert module_runner.os.environ["CONSUMER_SECRET"] == "consumer-secret"
    assert module_runner.os.environ["ACCESS_TOKEN"] == "access-token"
    assert module_runner.os.environ["ACCESS_SECRET"] == "access-secret"


def test_activate_module_oauth_rejects_missing_credentials(monkeypatch):
    import module_runner
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": "managed",
            "repo": "https://example.invalid/managed",
            "entry_point": "managed.service:run",
            "worker_jobs": [
                {
                    "name": "sync",
                    "handler": "managed.service:run",
                }
            ],
            "oauth_consumer_mode": "module",
            "oauth_consumer_key_env": "MANAGED_CONSUMER_TOKEN",
            "oauth_consumer_secret_env": "MANAGED_CONSUMER_SECRET",
        }
    )
    for name in (
        "MANAGED_CONSUMER_TOKEN",
        "MANAGED_CONSUMER_SECRET",
        "ACCESS_TOKEN",
        "ACCESS_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match="MANAGED_CONSUMER_TOKEN"):
        module_runner._activate_module_oauth(definition)
