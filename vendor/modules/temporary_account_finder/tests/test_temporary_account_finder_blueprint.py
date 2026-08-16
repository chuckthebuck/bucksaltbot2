from __future__ import annotations

from flask import Flask

from temporary_account_finder import blueprint as blueprint_module


def create_client(monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(blueprint_module.blueprint)
    monkeypatch.setattr(blueprint_module, "_has_access", lambda username: True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["username"] = "Example"
        session["access_token"] = {"key": "access", "secret": "secret"}
    return client


def test_access_api_is_no_store(monkeypatch):
    client = create_client(monkeypatch)
    monkeypatch.setattr(
        blueprint_module,
        "check_access",
        lambda *args, **kwargs: {
            "wiki": {"host": "meta.wikimedia.org"},
            "username": "Example",
            "eligible": True,
        },
    )
    response = client.get(
        "/api/v1/modules/temporary_account_finder/api/access?wiki=meta"
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.json["eligible"] is True


def test_search_api_rejects_unknown_fields(monkeypatch):
    client = create_client(monkeypatch)
    response = client.post(
        "/api/v1/modules/temporary_account_finder/api/search",
        json={"wiki": "meta", "accounts": "~2026-100", "store_results": True},
    )
    assert response.status_code == 400
    assert response.json["code"] == "invalid_request"


def test_search_api_rejects_non_boolean_ip_option(monkeypatch):
    client = create_client(monkeypatch)
    response = client.post(
        "/api/v1/modules/temporary_account_finder/api/search",
        json={"wiki": "meta", "accounts": "~2026-100", "include_ips": "yes"},
    )
    assert response.status_code == 400
    assert response.json["code"] == "invalid_request"


def test_api_requires_framework_module_access(monkeypatch):
    client = create_client(monkeypatch)
    monkeypatch.setattr(blueprint_module, "_has_access", lambda username: False)
    response = client.get(
        "/api/v1/modules/temporary_account_finder/api/access?wiki=meta"
    )
    assert response.status_code == 403
    assert response.json["code"] == "module_access_required"
