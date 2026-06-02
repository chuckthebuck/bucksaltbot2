from chuck_file_changer.config import (
    DEFAULT_USER_AGENT,
    http_headers,
    module_version,
    user_agent,
)


def test_default_user_agent_is_module_specific(monkeypatch):
    monkeypatch.delenv("CHUCK_FILE_CHANGER_USER_AGENT", raising=False)
    monkeypatch.delenv("CHUCK_FILE_CHANGER_HTTP_USER_AGENT", raising=False)

    assert user_agent() == DEFAULT_USER_AGENT
    assert http_headers()["User-Agent"] == DEFAULT_USER_AGENT
    assert DEFAULT_USER_AGENT.startswith(f"ChuckFileChanger/{module_version()} ")


def test_user_agent_env_override(monkeypatch):
    monkeypatch.setenv("CHUCK_FILE_CHANGER_USER_AGENT", "CustomUA/1.0")

    assert user_agent() == "CustomUA/1.0"


def test_blank_user_agent_env_override_uses_default(monkeypatch):
    monkeypatch.setenv("CHUCK_FILE_CHANGER_USER_AGENT", "  ")
    monkeypatch.delenv("CHUCK_FILE_CHANGER_HTTP_USER_AGENT", raising=False)

    assert user_agent() == DEFAULT_USER_AGENT
