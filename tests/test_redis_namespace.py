"""Redis namespace configuration tests."""

import pytest

from redis_namespace import celery_queue_name, redis_namespace


def test_redis_namespace_defaults_to_buckbot(monkeypatch):
    monkeypatch.delenv("BUCKBOT_REDIS_NAMESPACE", raising=False)

    assert redis_namespace() == "buckbot"
    assert celery_queue_name() == "buckbot.celery"


def test_custom_namespace_drives_default_celery_queue(monkeypatch):
    monkeypatch.setenv("BUCKBOT_REDIS_NAMESPACE", "buckbot-staging")
    monkeypatch.delenv("BUCKBOT_CELERY_QUEUE", raising=False)

    assert redis_namespace() == "buckbot-staging"
    assert celery_queue_name() == "buckbot-staging.celery"


def test_explicit_celery_queue_is_supported(monkeypatch):
    monkeypatch.setenv("BUCKBOT_CELERY_QUEUE", "buckbot.priority")

    assert celery_queue_name() == "buckbot.priority"


def test_application_uses_namespaced_celery_broker_and_results():
    from app import flask_app

    celery_config = flask_app.config["CELERY"]
    assert celery_config["task_default_queue"] == "buckbot.celery"
    assert celery_config["task_default_exchange"] == "buckbot.celery"
    assert celery_config["task_default_routing_key"] == "buckbot.celery"
    assert celery_config["broker_transport_options"] == {
        "global_keyprefix": "buckbot:"
    }
    assert celery_config["result_backend_transport_options"] == {
        "global_keyprefix": "buckbot"
    }


@pytest.mark.parametrize("variable", ["BUCKBOT_REDIS_NAMESPACE", "BUCKBOT_CELERY_QUEUE"])
def test_redis_names_reject_unsafe_values(monkeypatch, variable):
    monkeypatch.setenv(variable, "not valid/name")

    with pytest.raises(RuntimeError, match=variable):
        redis_namespace() if variable == "BUCKBOT_REDIS_NAMESPACE" else celery_queue_name()
