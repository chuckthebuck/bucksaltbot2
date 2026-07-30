"""Framework integration checks for the vendored Chuck the Salt Shack module."""

from pathlib import Path
import sys
from unittest.mock import patch

import pytest


SALT_SHACK_ROOT = (
    Path(__file__).resolve().parents[1]
    / "vendor"
    / "modules"
    / "chuck_salt_shack"
)
sys.path.insert(0, str(SALT_SHACK_ROOT / "modules"))


@pytest.fixture(autouse=True)
def _restore_shared_flask_setup_state():
    """Keep integration requests from locking later blueprint tests."""
    import router

    had_first_request = router.app._got_first_request
    yield
    router.app._got_first_request = had_first_request


def test_salt_shack_manifest_is_default_enabled_and_forkable():
    from router.module_registry import load_enabled_module_names, load_module_definition

    definition = load_module_definition(
        SALT_SHACK_ROOT / "modules" / "chuck_salt_shack" / "module.toml"
    )

    assert definition.name == "chuck_salt_shack"
    assert definition.title == "Salt Shack"
    assert (
        definition.repo_url
        == "https://github.com/chuckthebuck/chuck-the-salt-shack"
    )
    assert definition.ui_enabled is True
    assert [job.name for job in definition.worker_jobs] == ["preview", "apply"]
    assert definition.worker_jobs[1].required_right == "apply_changes"
    assert definition.frontend is not None
    assert definition.frontend.bundled is False
    assert "chuck_salt_shack" in load_enabled_module_names()
    assert (SALT_SHACK_ROOT / "pyproject.toml").is_file()
    assert (
        SALT_SHACK_ROOT
        / "modules"
        / "chuck_salt_shack"
        / "static"
        / "chuck-salt-shack-app.js"
    ).is_file()
    assert (
        SALT_SHACK_ROOT
        / "modules"
        / "chuck_salt_shack"
        / "assets"
        / "salt-shack-logo.svg"
    ).is_file()
    assert (
        SALT_SHACK_ROOT
        / "modules"
        / "chuck_salt_shack"
        / "generated"
        / "saltlick-registry.yaml"
    ).is_file()


def test_salt_shack_entry_point_loads_packaged_manifest():
    from chuck_salt_shack.manifest import module_manifest

    manifest = module_manifest()

    assert manifest["name"] == "chuck_salt_shack"
    assert manifest["frontend"]["bundled"] is False


def test_salt_shack_is_mounted_and_served_by_framework_ui():
    import router
    from router.module_registry import ModuleRecord, load_module_definition

    router.app.config["TESTING"] = True
    router.app.config["SECRET_KEY"] = "test-secret"
    client = router.app.test_client()
    definition = load_module_definition(
        SALT_SHACK_ROOT / "modules" / "chuck_salt_shack" / "module.toml"
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
        page_response = client.get("/modules/chuck_salt_shack/ui")
        asset_response = client.get(
            "/module-assets/chuck_salt_shack/"
            "chuck_salt_shack:static/chuck-salt-shack-app.js"
        )

    assert page_response.status_code == 200
    html = page_response.get_data(as_text=True)
    assert "Chuck the Buckbot Framework" in html
    assert 'id="chuck-salt-shack-app"' in html
    assert 'id="chuck-salt-shack-props"' in html
    assert (
        "/module-assets/chuck_salt_shack/"
        "chuck_salt_shack:static/chuck-salt-shack-app.js"
    ) in html
    assert '"can_manage": true' in html
    assert '"can_run": true' in html

    assert asset_response.status_code == 200
    assert asset_response.headers["Content-Type"].startswith("text/javascript")
    assert b"chuck-salt-shack-app" in asset_response.data


def test_framework_runtime_loads_real_salt_shack_blueprint():
    from router.module_registry import ModuleRecord, load_module_definition
    from router.module_runtime import load_module

    definition = load_module_definition(
        SALT_SHACK_ROOT / "modules" / "chuck_salt_shack" / "module.toml"
    )

    loaded = load_module(ModuleRecord(definition=definition, enabled=True))

    assert loaded.blueprint is not None
    assert loaded.blueprint.url_prefix == "/api/v1/modules/chuck_salt_shack"
