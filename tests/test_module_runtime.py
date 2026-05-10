"""Tests for router.module_runtime – runtime context and module registration."""

from unittest.mock import MagicMock, patch

from flask import Blueprint, Flask


def _make_record(module_name: str = "four_award"):
    import router.module_registry as registry

    definition = registry.parse_module_definition(
        {
            "name": module_name,
            "repo": "https://example.invalid/four-award",
            "entry_point": "four_award.handler",
            "ui": True,
        }
    )
    return registry.ModuleRecord(definition=definition, enabled=True)


def test_build_module_context_returns_access_for_enabled_module():
    import router.module_runtime as runtime

    record = _make_record()

    with (
        patch("router.module_runtime.get_module_definition", return_value=record),
        patch("router.module_runtime.is_maintainer", return_value=False),
        patch("router.module_runtime.user_has_module_access", return_value=True),
    ):
        context = runtime.build_module_context("four_award", username="Alice")

    assert context is not None
    assert context.module_name == "four_award"
    assert context.has_access is True
    assert context.redis_namespace == "four_award"


def test_register_enabled_modules_registers_blueprint_with_module_prefix():
    import router.module_runtime as runtime

    app = Flask(__name__)
    blueprint = Blueprint("four_award", __name__)
    record = _make_record()
    loaded = runtime.LoadedModule(record=record, blueprint=blueprint)

    with patch("router.module_runtime.load_enabled_modules", return_value=[loaded]):
        app.register_blueprint = MagicMock()
        registered = runtime.register_enabled_modules(app)

    assert registered == ["four_award"]
    app.register_blueprint.assert_called_once_with(blueprint, url_prefix="/four_award")
