import importlib


def test_framework_http_headers_include_default_user_agent(monkeypatch):
    monkeypatch.delenv("BUCKBOT_HTTP_USER_AGENT", raising=False)

    import http_config

    config = importlib.reload(http_config)

    assert config.http_headers()["User-Agent"].startswith("Buckbot/")


def test_framework_http_headers_allow_env_override(monkeypatch):
    monkeypatch.setenv("BUCKBOT_HTTP_USER_AGENT", "Buckbot-test/1.2")

    import http_config

    config = importlib.reload(http_config)

    assert config.http_headers() == {"User-Agent": "Buckbot-test/1.2"}


def test_framework_http_headers_merge_extra_headers(monkeypatch):
    monkeypatch.setenv("BUCKBOT_HTTP_USER_AGENT", "Buckbot-test/1.2")

    import http_config

    config = importlib.reload(http_config)

    assert config.http_headers({"Accept": "application/json"}) == {
        "User-Agent": "Buckbot-test/1.2",
        "Accept": "application/json",
    }
