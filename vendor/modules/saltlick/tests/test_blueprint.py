from flask import Flask

import saltlick.blueprint as api


def recipe():
    return {
        "version": 1,
        "name": "Example bot",
        "wiki": {"code": "commons", "family": "commons"},
        "source": {
            "type": "titles",
            "titles": ["User:Example/Sandbox"],
            "limit": 1,
        },
        "transforms": [
            {"type": "literal_replace", "find": "old", "replace": "new"}
        ],
        "save": {"summary": "Example"},
        "limits": {"max_edits": 1},
    }


def client(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(api.blueprint)
    monkeypatch.setattr(api, "_has_access", lambda _username: True)
    monkeypatch.setattr(api, "_has_right", lambda _username, _right: True)
    test_client = app.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["username"] = "Alice"
    return test_client


def test_validate_returns_fork_ready_files(monkeypatch):
    response = client(monkeypatch).post(
        "/api/v1/modules/saltlick/validate",
        json={"recipe": recipe()},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["recipe"]["name"] == "Example bot"
    assert "def run(ctx, payload)" in body["jobs_py"]
    assert 'name = "example_bot"' in body["module_toml"]


def test_apply_requires_explicit_live_confirmation(monkeypatch):
    response = client(monkeypatch).post(
        "/api/v1/modules/saltlick/apply",
        json={"recipe": recipe()},
    )

    assert response.status_code == 400
    assert "confirm_live" in response.get_json()["detail"]


def test_run_endpoint_rejects_script_and_handler_fields(monkeypatch):
    response = client(monkeypatch).post(
        "/api/v1/modules/saltlick/preview",
        json={
            "recipe": recipe(),
            "script": "print('no')",
            "handler": "other.module:run",
        },
    )

    assert response.status_code == 400
    assert "unsupported request field" in response.get_json()["detail"]


def test_preview_queues_canonical_recipe(monkeypatch):
    captured = {}

    def fake_enqueue(workflow, *, username, live, invocation):
        captured.update(
            workflow=workflow,
            username=username,
            live=live,
            invocation=invocation,
        )
        return 42

    monkeypatch.setattr(api, "_enqueue", fake_enqueue)
    response = client(monkeypatch).post(
        "/api/v1/modules/saltlick/preview",
        json={"recipe": recipe()},
    )

    assert response.status_code == 202
    assert response.get_json()["run_id"] == 42
    assert captured["username"] == "Alice"
    assert captured["live"] is False
    assert captured["workflow"].name == "Example bot"
