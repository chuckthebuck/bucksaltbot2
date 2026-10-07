"""Deployment wiring checks for vendored modules."""

import json
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[1]


def _enabled_module_names() -> set[str]:
    names: set[str] = set()
    for raw_line in (ROOT / "enabled-modules.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            names.add(line)
    return names


def _requirements_module_paths() -> set[str]:
    paths: set[str] = set()
    for raw_line in (ROOT / "requirements-modules.txt").read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line.startswith("./vendor/modules/"):
            paths.add(line)
    return paths


def test_frontend_modules_are_enabled_and_installed_for_runtime_discovery():
    raw_config = json.loads(
        (ROOT / "module-frontend-packages.json").read_text(encoding="utf-8")
    )
    frontend_modules = {
        item["name"]
        for item in raw_config.get("modules", [])
        if item.get("enabled") is not False and item.get("name")
    }

    enabled_modules = _enabled_module_names()
    requirement_paths = _requirements_module_paths()

    assert frontend_modules <= enabled_modules
    assert {
        f"./vendor/modules/{module_name}" for module_name in frontend_modules
    } <= requirement_paths


def test_self_delete_frontend_is_in_generated_bundle_registry():
    """Self Delete's source entry is selected and imported by the root UI build."""
    raw_config = json.loads(
        (ROOT / "module-frontend-packages.json").read_text(encoding="utf-8")
    )
    self_delete = next(
        item for item in raw_config["modules"] if item["name"] == "self_delete"
    )
    generated = (ROOT / "client-src" / "moduleRegistry.generated.ts").read_text(
        encoding="utf-8"
    )

    assert self_delete["enabled"] is True
    assert self_delete["import"] in generated


def test_self_delete_manifest_loads_as_ui_enabled_module():
    """The framework loader accepts the pinned standalone module manifest."""
    from router.module_registry import load_module_definition

    definition = load_module_definition(
        ROOT
        / "vendor"
        / "modules"
        / "self_delete"
        / "modules"
        / "self_delete"
        / "module.toml"
    )

    assert definition.name == "self_delete"
    assert definition.ui_enabled is True
    assert definition.frontend is not None
    assert definition.frontend.bundled is True


def test_vendored_entry_point_packages_ship_toml_manifest():
    for module_name in (
        "four_award",
        "chuck_file_changer",
        "chuck_salt_shack",
        "temporary_account_finder",
        "self_delete",
    ):
        pyproject = tomllib.loads(
            (ROOT / "vendor" / "modules" / module_name / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        package_data = pyproject["tool"]["setuptools"]["package-data"]

        assert any(
            "module.toml" in resources
            for resources in package_data.values()
        )


def test_toolforge_web_process_imports_module_bootstrap_application():
    start_script = (ROOT / "scripts" / "start_gunicorn.sh").read_text(
        encoding="utf-8"
    )

    assert "app:flask_app" in start_script
    assert "router:app" not in start_script
    assert 'ENABLE_MODULE_LOADING="${ENABLE_MODULE_LOADING:-1}"' in start_script
    assert 'cd "$REPO_ROOT"' in start_script


def test_toolforge_celery_worker_uses_its_isolated_queue():
    start_script = (ROOT / "scripts" / "start_celery.sh").read_text(
        encoding="utf-8"
    )

    assert 'CELERY_QUEUE="${BUCKBOT_CELERY_QUEUE:-${REDIS_NAMESPACE}.celery}"' in start_script
    assert '--queues "$CELERY_QUEUE"' in start_script
    assert '--hostname "${CELERY_WORKER_NAME}@%h"' in start_script


def test_celery_worker_registers_optional_self_delete_tasks():
    """The shared worker imports the module task without requiring its tables."""
    worker_source = (ROOT / "celery_worker.py").read_text(encoding="utf-8")

    assert "import self_delete.queue" in worker_source
    assert "except ModuleNotFoundError" in worker_source


def test_vendored_updater_tracks_self_delete_repository():
    """Snapshot refreshes include the standalone Self Delete source repository."""
    updater = (ROOT / "scripts" / "update-vendored-modules.sh").read_text(
        encoding="utf-8"
    )

    assert '"vendor/modules/self_delete"' in updater
    assert "SELF_DELETE_REMOTE" in updater
    assert "SELF_DELETE_BRANCH" in updater
    assert "chuckthebuck/chuck-self-delete.git" in updater


def test_toolforge_celery_ping_loads_the_configured_application():
    ping_script = (ROOT / "scripts" / "ping_celery.sh").read_text(
        encoding="utf-8"
    )

    assert 'cd "$REPO_ROOT"' in ping_script
    assert "python -m celery -A celery_worker:app inspect ping" in ping_script
