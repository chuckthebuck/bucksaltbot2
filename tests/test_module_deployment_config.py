"""Deployment wiring checks for vendored modules."""

from pathlib import Path
import json
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


def test_vendored_entry_point_packages_ship_toml_manifest():
    for module_name in (
        "four_award",
        "chuck_file_changer",
        "chuck_salt_shack",
        "temporary_account_finder",
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


def test_toolforge_celery_ping_loads_the_configured_application():
    ping_script = (ROOT / "scripts" / "ping_celery.sh").read_text(
        encoding="utf-8"
    )

    assert 'cd "$REPO_ROOT"' in ping_script
    assert "python -m celery -A celery_worker:app inspect ping" in ping_script
