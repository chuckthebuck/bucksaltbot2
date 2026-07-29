from pathlib import Path
import sys


SALTLICK_ROOT = (
    Path(__file__).resolve().parents[1]
    / "vendor"
    / "modules"
    / "saltlick"
)
sys.path.insert(0, str(SALTLICK_ROOT / "modules"))


def test_saltlick_manifest_is_default_enabled_and_forkable():
    from router.module_registry import load_enabled_module_names, load_module_definition

    definition = load_module_definition(
        SALTLICK_ROOT / "modules" / "saltlick" / "module.toml"
    )

    assert definition.name == "saltlick"
    assert definition.ui_enabled is True
    assert [job.name for job in definition.worker_jobs] == ["preview", "apply"]
    assert definition.worker_jobs[1].required_right == "apply_changes"
    assert definition.frontend is not None
    assert definition.frontend.bundled is False
    assert "saltlick" in load_enabled_module_names()
    assert (SALTLICK_ROOT / "pyproject.toml").is_file()
    assert (
        SALTLICK_ROOT
        / "modules"
        / "saltlick"
        / "static"
        / "saltlick-app.js"
    ).is_file()


def test_saltlick_entry_point_loads_packaged_manifest():
    from saltlick.manifest import module_manifest

    manifest = module_manifest()

    assert manifest["name"] == "saltlick"
    assert manifest["frontend"]["bundled"] is False
