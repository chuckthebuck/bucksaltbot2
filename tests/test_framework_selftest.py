from pathlib import Path

import framework_selftest


def _module_definition(**overrides):
    from router.module_registry import parse_module_definition

    payload = {
        "name": "sample_module",
        "repo": "https://example.invalid/sample-module",
        "entry_point": "sample_module.service:run",
        "ui": False,
        "worker_jobs": [
            {
                "name": "sample-job",
                "handler": "sample_module.service:run",
            }
        ],
    }
    payload.update(overrides)
    return parse_module_definition(payload)


def test_selftest_result_status_prioritizes_fatal_failures():
    result = framework_selftest.SelfTestResult(
        (
            framework_selftest.SelfTestCheck(
                name="warning",
                severity=framework_selftest.WARNING,
                ok=False,
                message="warning",
            ),
            framework_selftest.SelfTestCheck(
                name="fatal",
                severity=framework_selftest.FATAL,
                ok=False,
                message="fatal",
            ),
        )
    )

    assert result.status == framework_selftest.FATAL
    assert result.exit_code() == 1


def test_selftest_result_strict_fails_on_warnings():
    result = framework_selftest.SelfTestResult(
        (
            framework_selftest.SelfTestCheck(
                name="warning",
                severity=framework_selftest.WARNING,
                ok=False,
                message="warning",
            ),
        )
    )

    assert result.status == framework_selftest.WARNING
    assert result.exit_code() == 0
    assert result.exit_code(strict=True) == 1


def test_run_selftest_reports_missing_enabled_modules(monkeypatch):
    monkeypatch.setattr(
        framework_selftest,
        "_import_dependencies",
        lambda: framework_selftest._check(
            "python_dependencies",
            framework_selftest.FATAL,
            True,
            "ok",
        ),
    )
    monkeypatch.setattr(
        framework_selftest,
        "_load_module_definitions",
        lambda: ({"sample_module"}, {}, {}, {}),
    )

    result = framework_selftest.run_selftest()

    assert result.status == framework_selftest.FATAL
    assert any(check.name == "enabled_modules_available" and not check.ok for check in result.checks)


def test_run_selftest_checks_handlers_and_frontend_resources(tmp_path, monkeypatch):
    asset = tmp_path / "module.js"
    asset.write_text("console.log('ok');\n", encoding="utf-8")
    definition = _module_definition(
        ui=True,
        frontend={
            "script": str(asset),
        },
    )

    monkeypatch.setattr(
        framework_selftest,
        "_import_dependencies",
        lambda: framework_selftest._check(
            "python_dependencies",
            framework_selftest.FATAL,
            True,
            "ok",
        ),
    )
    monkeypatch.setattr(
        framework_selftest,
        "_load_module_definitions",
        lambda: ({"sample_module"}, {}, {"sample_module": definition}, {"sample_module": definition}),
    )
    resolved_handlers = []
    monkeypatch.setattr(
        framework_selftest,
        "_resolve_handler_module",
        lambda handler: resolved_handlers.append(handler),
    )

    result = framework_selftest.run_selftest()

    assert result.status == framework_selftest.OK
    assert resolved_handlers == ["sample_module.service:run"]


def test_run_selftest_reports_missing_frontend_resources(monkeypatch):
    definition = _module_definition(
        ui=True,
        frontend={
            "script": str(Path("/missing/sample-module.js")),
        },
    )
    monkeypatch.setattr(
        framework_selftest,
        "_import_dependencies",
        lambda: framework_selftest._check(
            "python_dependencies",
            framework_selftest.FATAL,
            True,
            "ok",
        ),
    )
    monkeypatch.setattr(
        framework_selftest,
        "_load_module_definitions",
        lambda: ({"sample_module"}, {}, {"sample_module": definition}, {"sample_module": definition}),
    )
    monkeypatch.setattr(framework_selftest, "_resolve_handler_module", lambda _handler: None)

    result = framework_selftest.run_selftest()

    assert result.status == framework_selftest.FATAL
    assert any(check.name == "module_frontend_resources" and not check.ok for check in result.checks)
