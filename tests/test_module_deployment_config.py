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
    for module_name in ("four_award", "chuck_file_changer"):
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
