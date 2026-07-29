def test_ensure_pywikibot_env_preserves_user_managed_config(tmp_path, monkeypatch):
    import pywikibot_env

    config_file = tmp_path / "user-config.py"
    custom = "family = 'wikipedia'\n# intentionally user managed\n"
    config_file.write_text(custom, encoding="utf-8")
    monkeypatch.setenv("PYWIKIBOT_DIR", str(tmp_path))

    resolved = pywikibot_env.ensure_pywikibot_env()

    assert resolved == tmp_path
    assert config_file.read_text(encoding="utf-8") == custom


def test_ensure_pywikibot_env_updates_framework_managed_config(tmp_path, monkeypatch):
    import pywikibot_env

    config_file = tmp_path / "user-config.py"
    config_file.write_text(
        pywikibot_env._GENERATED_CONFIG_MARKER + "\n# old\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYWIKIBOT_DIR", str(tmp_path))

    pywikibot_env.ensure_pywikibot_env(bot_username="ExampleBot")

    generated = config_file.read_text(encoding="utf-8")
    assert generated.startswith(pywikibot_env._GENERATED_CONFIG_MARKER)
    assert "ExampleBot" in generated
    assert "'*.wikipedia.org'" in generated


def test_ensure_pywikibot_env_creates_framework_managed_config(tmp_path, monkeypatch):
    import pywikibot_env

    monkeypatch.setenv("PYWIKIBOT_DIR", str(tmp_path))

    pywikibot_env.ensure_pywikibot_env()

    generated = (tmp_path / "user-config.py").read_text(encoding="utf-8")
    assert generated.startswith(pywikibot_env._GENERATED_CONFIG_MARKER)
