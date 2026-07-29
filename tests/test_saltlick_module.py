from pathlib import Path
import sys
from unittest.mock import patch


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
    assert definition.title == "Salt Shack"
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
    assert (
        SALTLICK_ROOT
        / "modules"
        / "saltlick"
        / "assets"
        / "salt-shack-logo.svg"
    ).is_file()
    assert (
        SALTLICK_ROOT
        / "modules"
        / "saltlick"
        / "generated"
        / "saltlick-registry.yaml"
    ).is_file()


def test_saltlick_entry_point_loads_packaged_manifest():
    from saltlick.manifest import module_manifest

    manifest = module_manifest()

    assert manifest["name"] == "saltlick"
    assert manifest["frontend"]["bundled"] is False


def test_salt_shack_is_mounted_and_served_by_framework_ui():
    import router
    from router.module_registry import ModuleRecord, load_module_definition

    router.app.config["TESTING"] = True
    router.app.config["SECRET_KEY"] = "test-secret"
    client = router.app.test_client()
    definition = load_module_definition(
        SALTLICK_ROOT / "modules" / "saltlick" / "module.toml"
    )
    record = ModuleRecord(definition=definition, enabled=True)
    with client.session_transaction() as session:
        session["username"] = "alice"

    with (
        patch("router.routes.get_module_definition", return_value=record),
        patch("router.routes._can_view_module_jobs", return_value=True),
        patch("router.routes._can_manage_module", return_value=True),
        patch("router.routes._can_run_module_jobs", return_value=True),
        patch("router.routes._can_edit_module_config", return_value=False),
        patch("router.routes.user_has_module_access", return_value=True),
    ):
        page_response = client.get("/modules/saltlick/ui")
        asset_response = client.get(
            "/module-assets/saltlick/saltlick:static/saltlick-app.js"
        )

    assert page_response.status_code == 200
    html = page_response.get_data(as_text=True)
    assert "Chuck the Buckbot Framework" in html
    assert 'id="saltlick-app"' in html
    assert 'id="saltlick-props"' in html
    assert "/module-assets/saltlick/saltlick:static/saltlick-app.js" in html
    assert '"can_manage": true' in html
    assert '"can_run": true' in html

    assert asset_response.status_code == 200
    assert asset_response.headers["Content-Type"].startswith("text/javascript")
    assert b"saltlick-app" in asset_response.data


def test_framework_runtime_loads_real_salt_shack_blueprint():
    from router.module_registry import ModuleRecord, load_module_definition
    from router.module_runtime import load_module

    definition = load_module_definition(
        SALTLICK_ROOT / "modules" / "saltlick" / "module.toml"
    )

    loaded = load_module(ModuleRecord(definition=definition, enabled=True))

    assert loaded.blueprint is not None
    assert loaded.blueprint.url_prefix == "/api/v1/modules/saltlick"
