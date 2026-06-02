from unittest.mock import patch


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
