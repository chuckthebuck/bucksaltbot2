"""Tests for generated vendored-module requirements."""

from pathlib import Path
import runpy


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update-module-requirements.py"
MODULE = runpy.run_path(str(SCRIPT))


def test_generated_requirements_match_the_checked_in_file():
    assert (ROOT / "requirements-modules.txt").read_text(encoding="utf-8") == MODULE[
        "render_requirements"
    ](ROOT)


def test_only_enabled_vendored_modules_are_emitted(tmp_path):
    (tmp_path / "enabled-modules.txt").write_text(
        "local_module\nexternal_module\n# disabled_module\n", encoding="utf-8"
    )
    module = tmp_path / "vendor" / "modules" / "external_module"
    module.mkdir(parents=True)
    (module / "pyproject.toml").write_text("[project]\nname = 'external'\n", encoding="utf-8")

    assert MODULE["render_requirements"](tmp_path).endswith(
        "./vendor/modules/external_module\n"
    )
