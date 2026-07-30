from flask import Flask

import chuck_salt_shack.blueprint as api


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
        "/api/v1/modules/chuck_salt_shack/validate",
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
        "/api/v1/modules/chuck_salt_shack/apply",
        json={"recipe": recipe()},
    )

    assert response.status_code == 400
    assert "confirm_live" in response.get_json()["detail"]


def test_run_endpoint_rejects_script_and_handler_fields(monkeypatch):
    response = client(monkeypatch).post(
        "/api/v1/modules/chuck_salt_shack/preview",
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
        "/api/v1/modules/chuck_salt_shack/preview",
        json={"recipe": recipe()},
    )

    assert response.status_code == 202
    assert response.get_json()["run_id"] == 42
    assert captured["username"] == "Alice"
    assert captured["live"] is False
    assert captured["workflow"].name == "Example bot"


def test_salt_shack_catalog_exposes_contracts_without_entrypoints(monkeypatch):
    response = client(monkeypatch).get("/api/v1/modules/chuck_salt_shack/saltlicks")

    assert response.status_code == 200
    body = response.get_json()
    assert body["module"]["display_name"] == "Salt Shack"
    assert {item["id"] for item in body["saltlicks"]} == {
        "page_purger",
        "transclusion_report",
    }
    assert all("entrypoint" not in item for item in body["saltlicks"])


def test_nested_run_endpoint_accepts_only_inputs_and_arguments(monkeypatch):
    captured = {}

    def fake_enqueue(
        saltlick_id,
        *,
        username,
        live,
        inputs,
        arguments,
        preview_token="",
    ):
        captured.update(
            saltlick_id=saltlick_id,
            username=username,
            live=live,
            inputs=inputs,
            arguments=arguments,
            preview_token=preview_token,
        )
        return 77

    monkeypatch.setattr(api, "_enqueue_saltlick", fake_enqueue)
    response = client(monkeypatch).post(
        "/api/v1/modules/chuck_salt_shack/saltlicks/page_purger/runs",
        json={
            "mode": "preview",
            "inputs": {
                "targets": [{"title": "Main Page", "namespace": 0}],
            },
            "arguments": ["-verbose"],
        },
    )

    assert response.status_code == 202
    assert response.get_json()["run_id"] == 77
    assert captured["saltlick_id"] == "page_purger"
    assert captured["username"] == "Alice"
    assert captured["live"] is False
    assert captured["inputs"]["targets"][0]["namespace"] == 0

    rejected = client(monkeypatch).post(
        "/api/v1/modules/chuck_salt_shack/saltlicks/page_purger/runs",
        json={
            "mode": "preview",
            "inputs": {
                "targets": [{"title": "Main Page", "namespace": 0}],
            },
            "script": "other.py",
        },
    )
    assert rejected.status_code == 400
    assert "unsupported request field" in rejected.get_json()["detail"]
