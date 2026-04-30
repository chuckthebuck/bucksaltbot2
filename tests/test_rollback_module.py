"""Tests for the bundled rollback module blueprint."""

from unittest.mock import patch

import pytest


@pytest.fixture()
def flask_app():
    import router

    router.app.config["TESTING"] = True
    router.app.config["SECRET_KEY"] = "test-secret"
    return router.app


@pytest.fixture()
def client(flask_app):
    return flask_app.test_client()


def _set_session(client, username):
    with client.session_transaction() as sess:
        sess["username"] = username


def _register_blueprint(client):
    import modules.rollback.blueprint as rollback_blueprint

    if rollback_blueprint.blueprint.name not in client.application.blueprints:
        client.application.register_blueprint(
            rollback_blueprint.blueprint,
            url_prefix="/rollback",
        )

    return rollback_blueprint


def test_rollback_module_index_requires_auth(client):
    _register_blueprint(client)

    resp = client.get("/rollback/")
    assert resp.status_code == 401


def test_rollback_module_index_renders_for_maintainer(client):
    import router.module_registry as registry

    _set_session(client, "maintainer")
    rollback_blueprint = _register_blueprint(client)

    record = registry.ModuleRecord(
        definition=registry.parse_module_definition(
            {
                "name": "rollback",
                "repo": "https://example.invalid/bucksaltbot2",
                "entry_point": "modules.rollback.blueprint",
                "ui": True,
                "buildpacks": ["heroku/python"],
            }
        ),
        enabled=True,
    )

    with patch.object(rollback_blueprint, "get_module_definition", return_value=record), patch.object(
        rollback_blueprint, "is_maintainer", return_value=True
    ):
        resp = client.get("/rollback/")

    assert resp.status_code == 200
    assert b"Rollback" in resp.data
    assert b"/rollback-queue" in resp.data
