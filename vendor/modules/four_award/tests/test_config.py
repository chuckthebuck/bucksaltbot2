"""Tests for version-aware Four Award HTTP identity configuration."""

import importlib


def test_default_user_agent_matches_module_version(monkeypatch):
    """The generated User-Agent advertises the resolved package version."""
    monkeypatch.delenv("FOUR_AWARD_HTTP_USER_AGENT", raising=False)

    from four_award import config

    reloaded = importlib.reload(config)

    assert reloaded.HTTP_USER_AGENT.startswith(
        f"FourAwardHelper/{reloaded.module_version()} "
    )


def test_blank_user_agent_env_override_uses_default(monkeypatch):
    """Whitespace-only overrides cannot erase the identified default agent."""
    monkeypatch.setenv("FOUR_AWARD_HTTP_USER_AGENT", "  ")

    from four_award import config

    reloaded = importlib.reload(config)

    assert reloaded.HTTP_USER_AGENT == reloaded.default_http_user_agent()
